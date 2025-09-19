from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from ..models import Alquiler, DetalleAlquiler, Acta
from alquiler.forms.alquiler_forms import (
    AlquilerForm,
    DocumentosAlquilerForm,
    FirmarContratoForm,
    DetalleAlquilerFormSet,
    DetalleAlquilerForm,
    ConvertirReservaForm, 
    RenovarAlquilerForm
)
from django.http import Http404 
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.core.mail import send_mail
import json
from ..models import Equipo, Contrato, Cliente
from xhtml2pdf import pisa
from io import BytesIO
from django.core.files.base import ContentFile
import base64
import re
from decimal import Decimal, ROUND_HALF_UP
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Case, When, Value, CharField
from PIL import Image
from django.core.exceptions import ValidationError
from datetime import datetime
from django.utils.safestring import mark_safe
from django.urls import reverse
from alquiler.utils import crear_pago_inicial  # Asegúrate de importar
from django.contrib.auth.decorators import login_required, permission_required
from django.forms import inlineformset_factory
from django.http import HttpResponseRedirect
from django.db.models import F
import os
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from email.mime.image import MIMEImage
import traceback
import logging
logger = logging.getLogger(__name__)



@login_required
@permission_required('alquiler.view_alquiler', raise_exception=True)
def listar_alquileres(request):
    # Filtrar por usuario creador si no es superusuario
    if request.user.is_superuser:
        alquileres = Alquiler.objects.all()
    else:
        alquileres = Alquiler.objects.filter(creado_por=request.user)
    
    alquileres = alquileres.select_related('cliente').prefetch_related('detalles__equipo').order_by('-id')
    
    # Resto del código de filtrado permanece igual...
    estado = request.GET.get('estado')
    cliente = request.GET.get('cliente')
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    buscador_factura = request.GET.get('buscador_factura')
    
    if estado:
        alquileres = alquileres.filter(estado_alquiler=estado)
    if cliente:
        alquileres = alquileres.filter(cliente__nombre__icontains=cliente)
    if fecha_inicio:
        alquileres = alquileres.filter(fecha_inicio__gte=fecha_inicio)
    if fecha_fin:
        alquileres = alquileres.filter(fecha_fin__lte=fecha_fin)
    if buscador_factura:
        alquileres = alquileres.filter(numero_factura__icontains=buscador_factura)
    
    # Paginación
    paginator = Paginator(alquileres, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'alquileres': page_obj,
        'estados_alquiler': Alquiler.ESTADO_ALQUILER,
        'estado_seleccionado': estado,
        'is_paginated': page_obj.has_other_pages(),
        'buscador_factura': buscador_factura,
        'page_obj': page_obj,
        'show_alquileres_vencer_button': True,  # Nuevo contexto para mostrar el botón
    }
    
    return render(request, 'lista_alquileres.html', context)

# =========================
# VISTA
# =========================

@login_required
@permission_required('alquiler.send_notifications', raise_exception=True)
def alquileres_a_vencer(request):
    hoy = timezone.now().date()
    fecha_limite = hoy + timedelta(days=7)
    
    # Filtrar por usuario creador si no es superusuario
    if request.user.is_superuser:
        alquileres = Alquiler.objects.filter(
            fecha_fin__range=[hoy, fecha_limite],
            estado_alquiler='activo'
        )
    else:
        alquileres = Alquiler.objects.filter(
            fecha_fin__range=[hoy, fecha_limite],
            estado_alquiler='activo',
            creado_por=request.user
        )
    
    alquileres = (
        alquileres
        .select_related('cliente')
        .prefetch_related('detalles__equipo')
        .order_by('fecha_fin')
    )
    
    # Calcular días restantes para cada alquiler
    for alquiler in alquileres:
        alquiler.dias_restantes = (alquiler.fecha_fin - hoy).days
    
    if request.method == 'POST':
        selected_ids = request.POST.getlist('alquileres_seleccionados')
        if selected_ids:
            alquileres_seleccionados = Alquiler.objects.filter(id__in=selected_ids)
            enviar_alertas_vencimiento(alquileres_seleccionados)  # ✅ ahora sí recibe queryset
            messages.success(
                request,
                f"Se han enviado alertas para {len(selected_ids)} alquiler(es) seleccionado(s)."
            )
            return redirect('alquiler:listar_alquileres')
        else:
            messages.warning(request, "No seleccionaste ningún alquiler para notificar.")
    
    return render(request, 'alquileres_a_vencer.html', {
        'alquileres': alquileres,
        'hoy': hoy,
        'fecha_limite': fecha_limite,
    })


# =========================
# HELPER
# =========================
def enviar_alertas_vencimiento(alquileres_por_vencer):
    hoy = timezone.now().date()
    
    if not alquileres_por_vencer.exists():
        print("📭 No hay alquileres seleccionados para notificar")
        return

    sent_count = 0
    error_count = 0

    grouped_alquileres = {}
    for alquiler in alquileres_por_vencer:
        key = (alquiler.cliente, alquiler.numero_factura)
        grouped_alquileres.setdefault(key, []).append(alquiler)

    for (cliente, factura), alquileres_list in grouped_alquileres.items():
        try:
            primer_alquiler = alquileres_list[0]
            dias_restantes = (primer_alquiler.fecha_fin - hoy).days

            equipos_info = []
            for alq in alquileres_list:
                for detalle in alq.detalles.all():
                    equipo = detalle.equipo
                    equipos_info.append({
                        'nombre': f"{equipo.marca} {equipo.modelo}",
                        'sku': equipo.sku or "N/A"
                    })

            # --- Tipo de notificación ---
            if dias_restantes <= 3:
                tipo_notificacion = "terminacion"
                notificacion_legal = (
                    "Notificación Terminación de contrato..."
                )
            else:
                tipo_notificacion = "renovacion"
                notificacion_legal = (
                    "Notificación Renovación de contrato..."
                )

            contexto = {
                'nombre_cliente': cliente.nombre,
                'numero_factura': factura,
                'fecha_inicio': primer_alquiler.fecha_inicio.strftime("%d/%m/%Y"),
                'fecha_fin': primer_alquiler.fecha_fin.strftime("%d/%m/%Y"),
                'dias_restantes': dias_restantes,
                'equipos_info': equipos_info,
                'cantidad_equipos': len(equipos_info),
                'precio_total': sum(alq.precio_total for alq in alquileres_list),
                'tipo_notificacion': tipo_notificacion,
                'notificacion_legal': notificacion_legal,
                'logo_empresa': 'cid:logo_tecnonacho',
            }

            # --- Render HTML del correo ---
            html_content = render_to_string('alerta_vencimiento.html', contexto)
            text_content = strip_tags(html_content)

            # --- Crear objeto de correo (SIEMPRE ANTES DE USARLO) ---
            email = EmailMultiAlternatives(
                subject=f'Alquiler #{factura} por vencer en {dias_restantes} día(s)',
                body=text_content,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'notificaciones@tecnonacho.com'),
                to=[cliente.email],
                reply_to=[getattr(settings, 'EMAIL_REPLY_TO', 'soporte@tecnonacho.com')],
            )
            email.attach_alternative(html_content, "text/html")

            # --- Adjuntar logo ---
            logo_path = os.path.join(settings.BASE_DIR, "alquiler", "static", "media", "tecnonacho.png")
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as logo_file:
                    logo = MIMEImage(logo_file.read())
                    logo.add_header('Content-ID', '<logo_tecnonacho>')
                    logo.add_header('Content-Disposition', 'inline', filename='logo_tecnonacho.png')
                    email.attach(logo)

            # --- Enviar correo ---
            email.send(fail_silently=False)
            sent_count += 1
            print(f"✅ Alerta enviada a: {cliente.email} (Factura: {factura})")

        except Exception as e:
            error_count += 1
            print(f"❌ Error al enviar a {cliente.email}: {str(e)}")
            traceback.print_exc()

    print(f"\n📤 Resumen: {sent_count} correos enviados, {error_count} errores")
    return sent_count

@login_required
@permission_required('alquiler.export_alquiler', raise_exception=True)
def generar_pdf_acta(alquiler, request):
    html = render_to_string('acta_entrega.html', {
        'alquiler': alquiler,
        'request': request
    })

    result = BytesIO()
    pisa_status = pisa.CreatePDF(
        html, dest=result, encoding='UTF-8',
        link_callback=lambda uri, _: request.build_absolute_uri(uri)
    )

    if pisa_status.err:
        raise Exception("El PDF no se pudo generar correctamente. Revisa el template HTML.")

    result.seek(0)
    return result.getvalue()


@login_required
@permission_required('alquiler.add_alquiler', raise_exception=True)
def crear_alquiler(request):
    cliente_id = request.GET.get('cliente')
    cliente = None

    if cliente_id:
        cliente = get_object_or_404(Cliente, uuid_id=cliente_id)
        print(f" Cliente: {cliente.nombre}, Moroso: {cliente.moroso}, Verificación: {cliente.estado_verificacion}")

        if cliente.moroso and not request.user.has_perm('alquiler.override_moroso'):
            messages.error(
                request,
                f"El cliente {cliente.nombre} está marcado como moroso y no puede realizar nuevos alquileres."
            )
            return redirect('alquiler:listar_clientes')

        if cliente.estado_verificacion != 'verificado':
            messages.error(
                request,
                f"El cliente {cliente.nombre} no está verificado. No puede realizar alquileres."
            )
            return redirect('alquiler:listar_clientes')

    equipos_disponibles = Equipo.objects.filter(cantidad_disponible__gt=0)

    if request.method == 'POST':
        print("📥 Procesando POST para crear alquiler")
        alquiler = Alquiler(es_reserva=False)
        form = AlquilerForm(request.POST, instance=alquiler, request=request)
        formset = DetalleAlquilerFormSet(request.POST, prefix='detalles')

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    alquiler = form.save(commit=False)
                    alquiler.creado_por = request.user
                    print(f"➡️ Cliente del alquiler: {alquiler.cliente.nombre}")

                    # Validaciones de negocio
                    if (alquiler.cliente.moroso and not form.cleaned_data.get('forzar_alquiler')) or \
                       alquiler.cliente.estado_verificacion != 'verificado':
                        messages.error(request, "No se puede crear alquiler para este cliente.")
                        return redirect('alquiler:crear_alquiler')

                    alquiler.estado_alquiler = 'activo'
                    alquiler.es_reserva = False
                    alquiler.aprobado_por = getattr(request.user, 'nombre_usuario', request.user.get_username())
                    alquiler.fecha_vencimiento = alquiler.fecha_fin

                    if not alquiler.numero_factura:
                        raise ValidationError("Debe ingresar un número de factura para alquileres activos")

                    alquiler.save()
                    print(f"✅ Alquiler guardado ID: {alquiler.id}")

                    # Guardar detalles del alquiler
                    for form_detalle in formset.forms:
                        if form_detalle.cleaned_data and not form_detalle.cleaned_data.get('DELETE', False):
                            detalle = form_detalle.save(commit=False)
                            detalle.alquiler = alquiler

                            # Normalizar números de serie
                            if isinstance(detalle.numeros_serie, str):
                                try:
                                    detalle.numeros_serie = json.loads(detalle.numeros_serie)
                                except json.JSONDecodeError:
                                    detalle.numeros_serie = [s.strip() for s in detalle.numeros_serie.split(',') if s.strip()]

                            if not isinstance(detalle.numeros_serie, list):
                                detalle.numeros_serie = []

                            # Cantidad según necesidad de serie
                            if detalle.equipo.requiere_serie:
                                detalle.cantidad = len(detalle.numeros_serie)
                            else:
                                detalle.cantidad = 1

                            # Precio si no fue seteado manualmente
                            if not detalle.precio_unitario:
                                periodo = detalle.periodo_alquiler
                                detalle.precio_unitario = getattr(detalle.equipo, f'precio_{periodo}', 0) or 0

                            detalle.save()
                            detalle.equipo.actualizar_disponibilidad()

                    alquiler.calcular_precio_total()
                    crear_pago_inicial(alquiler, aprobado_por=request.user)

                    messages.success(request, "Alquiler creado exitosamente.")
                    return redirect(f"{reverse('alquiler:listar_alquileres')}?alquiler_id={alquiler.id}")

            except Exception as e:
                messages.error(request, f"Error al guardar: {str(e)}")
                print(f"🚨 Excepción durante guardado: {str(e)}")
        else:
            print("❌ Formulario inválido")
            print(f"Errores form: {form.errors}")
            print(f"Errores formset: {[f.errors for f in formset]}")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error en {field}: {error}")
            for f in formset:
                for field, errors in f.errors.items():
                    for error in errors:
                        messages.error(request, f"Error en equipo ({field}): {error}")
    else:
        print("📄 Renderizando formulario GET")
        initial_data = {
            'fecha_inicio': timezone.now().date(),
            'fecha_fin': timezone.now().date() + timedelta(days=7),
            'con_iva': True
        }

        if cliente_id:
            initial_data['cliente'] = cliente_id

        form = AlquilerForm(initial=initial_data, request=request)
        formset = DetalleAlquilerFormSet(prefix='detalles')

    return render(request, 'crear_alquiler.html', {
        'form': form,
        'formset': formset,
        'equipos_disponibles': equipos_disponibles,
        'cliente_moroso': Cliente.objects.get(uuid_id=cliente_id).moroso if cliente_id else False
    })


@login_required
@permission_required('alquiler.change_alquiler', raise_exception=True)
def editar_alquiler(request, id):
    print(f"[INFO] Iniciando edición del alquiler ID: {id}")
    alquiler = get_object_or_404(Alquiler, uuid_id=id)

    print(f"[INFO] Alquiler cargado: Cliente={alquiler.cliente}, Fecha Fin={alquiler.fecha_fin}")

    equipos_disponibles = Equipo.objects.filter(
        Q(cantidad_disponible__gt=0) | Q(detallealquiler__alquiler=alquiler)
    ).distinct().annotate(
        requiere_serie_case=Case(
            When(requiere_serie=True, then=Value('True')),
            default=Value('False'),
            output_field=CharField()
        )
    )
    print(f"[INFO] Equipos disponibles encontrados: {equipos_disponibles.count()}")

    DetalleAlquilerFormSet = inlineformset_factory(
        Alquiler,
        DetalleAlquiler,
        form=DetalleAlquilerForm,
        extra=0,
        can_delete=True,
        fields=['equipo', 'numeros_serie', 'periodo_alquiler', 'cantidad', 'precio_unitario', 'con_iva']
    )

    if request.method == 'POST':
        print("[INFO] Método POST recibido.")
        form = AlquilerForm(request.POST, instance=alquiler, request=request)
        formset = DetalleAlquilerFormSet(request.POST, instance=alquiler, prefix='detalles')

        print(f"[DEBUG] ¿Formulario principal válido? {form.is_valid()}")

        if form.is_valid():
            try:
                with transaction.atomic():
                    detalles_data = []
                    total_forms = int(request.POST.get('detalles-TOTAL_FORMS', 0))
                    print(f"[INFO] Procesando {total_forms} formularios de detalle.")

                    for i in range(total_forms):
                        prefix = f'detalles-{i}'
                        if request.POST.get(f'{prefix}-DELETE') == 'on':
                            print(f"[INFO] Detalle #{i} marcado para eliminar. Saltando.")
                            continue

                        equipo_id = request.POST.get(f'{prefix}-equipo')
                        equipo = get_object_or_404(Equipo, uuid_id=equipo_id)
                        print(f"[DEBUG] Detalle #{i} -> Equipo ID: {equipo_id}")

                        numeros_serie = request.POST.get(f'{prefix}-numeros_serie', '[]')
                        try:
                            numeros_serie = json.loads(numeros_serie)
                        except json.JSONDecodeError:
                            numeros_serie = [s.strip() for s in numeros_serie.split(',') if s.strip()]
                        numeros_serie = [s for s in numeros_serie if s]

                        if equipo.requiere_serie and not numeros_serie:
                            print(f"[WARN] El equipo {equipo} requiere serie, pero no se encontró ninguna. Saltando.")
                            continue

                        detalles_data.append({
                            'id': request.POST.get(f'{prefix}-id'),
                            'equipo': equipo_id,
                            'numeros_serie': numeros_serie,
                            'periodo_alquiler': request.POST.get(f'{prefix}-periodo_alquiler'),
                            'cantidad': len(numeros_serie) if equipo.requiere_serie else 1,
                            'precio_unitario': request.POST.get(f'{prefix}-precio_unitario'),
                            'con_iva': request.POST.get(f'{prefix}-con_iva') == 'on',
                            'DELETE': False
                        })

                    if not detalles_data:
                        print("[ERROR] No se proporcionaron detalles válidos.")
                        form.add_error(None, 'Debe agregar al menos un equipo al alquiler')
                        raise forms.ValidationError('Debe agregar al menos un equipo al alquiler')

                    alquiler_actualizado = form.save(commit=False)
                    alquiler_actualizado.fecha_vencimiento = form.cleaned_data['fecha_fin']
                    alquiler_actualizado.save()
                    print(f"[INFO] Alquiler actualizado: ID={alquiler_actualizado.id}")

                    detalles_existentes = {d.id: d for d in alquiler.detalles.all()}
                    equipos_afectados = set()

                    for detalle_data in detalles_data:
                        if detalle_data['id']:
                            detalle = detalles_existentes.get(int(detalle_data['id']))
                            if not detalle:
                                print(f"[WARN] Detalle con ID {detalle_data['id']} no encontrado. Saltando.")
                                continue
                        else:
                            detalle = DetalleAlquiler(alquiler=alquiler_actualizado)

                        detalle.equipo_id = detalle_data['equipo']
                        detalle.numeros_serie = detalle_data['numeros_serie']
                        detalle.periodo_alquiler = detalle_data['periodo_alquiler']
                        detalle.cantidad = detalle_data['cantidad']
                        try:
                            detalle.precio_unitario = Decimal(str(detalle_data['precio_unitario']))
                        except:
                            detalle.precio_unitario = Decimal('0')
                        detalle.con_iva = detalle_data['con_iva']

                        print(f"[INFO] Guardando detalle -> Equipo: {detalle.equipo_id}, Cantidad: {detalle.cantidad}, Precio: {detalle.precio_unitario}")
                        detalle.save()
                        equipos_afectados.add(detalle.equipo)

                    detalles_a_eliminar = set(detalles_existentes.keys()) - {
                        int(d['id']) for d in detalles_data if d['id']
                    }
                    print(f"[INFO] Eliminando {len(detalles_a_eliminar)} detalles no presentes en el formulario.")
                    for detalle_id in detalles_a_eliminar:
                        detalle = detalles_existentes[detalle_id]
                        equipos_afectados.add(detalle.equipo)
                        detalle.delete()

                    print(f"[INFO] Actualizando disponibilidad de {len(equipos_afectados)} equipos.")
                    for equipo in equipos_afectados:
                        print(f"[DEBUG] Actualizando equipo UUID: {equipo.uuid_id}")
                        equipo.actualizar_disponibilidad()

                    alquiler_actualizado.calcular_precio_total()
                    print("[INFO] Precio total recalculado.")
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'success': True, 'redirect_url': reverse('alquiler:listar_alquileres')})
                    else:
                        return redirect('alquiler:listar_alquileres')
                    
            except Exception as e:
                import traceback
                print(f"[ERROR] Excepción durante la actualización: {str(e)}")
                traceback.print_exc()
                messages.error(request, f"Error al actualizar: {str(e)}")
                logger.error(f"Error al editar alquiler: {str(e)}", exc_info=True)

        else:
            print("[ERROR] El formulario principal no es válido.")
            for field, errors in form.errors.items():
                for error in errors:
                    print(f"[ERROR] Campo: {field} -> {error}")
                    messages.error(request, f"Error en {field}: {error}")

            for error in form.non_field_errors():
                print(f"[ERROR] Error general: {error}")
                messages.error(request, f"Error: {error}")

    else:
        print("[INFO] Método GET - cargando formulario existente.")
        form = AlquilerForm(instance=alquiler, request=request)
        formset = DetalleAlquilerFormSet(instance=alquiler, prefix='detalles')

    equipos_json = json.dumps([
        {
            "id": detalle.id,
            "equipoId": str(detalle.equipo.uuid_id),
            "equipoTexto": f"{detalle.equipo.marca} {detalle.equipo.modelo}",
            "series": [s for s in (detalle.numeros_serie if isinstance(detalle.numeros_serie, list) else []) if s],
            "periodo": detalle.periodo_alquiler,
            "periodoTexto": detalle.get_periodo_alquiler_display(),
            "precioUnitario": float(detalle.precio_unitario),
            "formIndex": i,
            "conIva": detalle.con_iva,
            "requiereSerie": detalle.equipo.requiere_serie
        }
        for i, detalle in enumerate(alquiler.detalles.all())
    ])
    print("[DEBUG] JSON de equipos enviado al frontend:")
    print(equipos_json)

    return render(request, 'editar_alquiler.html', {
        'form': form,
        'formset': formset,
        'alquiler': alquiler,
        'equipos_disponibles': equipos_disponibles,
        'equipos_json': mark_safe(equipos_json)
    })


@login_required
@permission_required('alquiler.add_alquiler', raise_exception=True)
def reservar_alquiler(request):
    equipos_disponibles = Equipo.objects.filter(cantidad_disponible__gt=0)
    DetalleAlquilerFormSet = inlineformset_factory(
        Alquiler,
        DetalleAlquiler,
        form=DetalleAlquilerForm,
        extra=1,
        can_delete=True,
        fields=['equipo', 'numeros_serie', 'periodo_alquiler', 'cantidad', 'precio_unitario', 'con_iva']
    )

    if request.method == 'POST':
        form = AlquilerForm(request.POST, request=request)
        form.instance.es_reserva = True
        formset = DetalleAlquilerFormSet(request.POST, prefix='detalles')

        cliente_id = request.POST.get('cliente')
        cliente = get_object_or_404(Cliente, pk=cliente_id)


        # Validación: moroso y no verificado
        if cliente:
            if cliente.moroso and not request.user.has_perm('alquiler.override_moroso'):
                messages.error(request, f"El cliente {cliente.nombre} está marcado como moroso y no puede reservar.")
                return redirect('alquiler:listar_clientes')
            if cliente.estado_verificacion != 'verificado':
                messages.error(request, f"El cliente {cliente.nombre} no está verificado.")
                return redirect('alquiler:listar_clientes')

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    alquiler = form.save(commit=False)
                    alquiler.estado_alquiler = 'reservado'
                    alquiler.es_reserva = True
                    alquiler.numero_factura = None  # Reservas no generan factura
                    alquiler.fecha_vencimiento = alquiler.fecha_fin  # Igualar fecha de vencimiento
                    alquiler.save()

                    for detalle in formset.save(commit=False):
                        detalle.alquiler = alquiler

                        if isinstance(detalle.numeros_serie, str):
                            try:
                                detalle.numeros_serie = json.loads(detalle.numeros_serie)
                            except json.JSONDecodeError:
                                detalle.numeros_serie = [
                                    s.strip() for s in detalle.numeros_serie.split(',') if s.strip()
                                ]

                        if not isinstance(detalle.numeros_serie, list):
                            detalle.numeros_serie = []

                        if detalle.equipo.requiere_serie:
                            detalle.cantidad = len(detalle.numeros_serie) if detalle.numeros_serie else detalle.cantidad or 1
                        else:
                            detalle.cantidad = 1

                        if not detalle.precio_unitario:
                            periodo = detalle.periodo_alquiler
                            equipo = detalle.equipo
                            detalle.precio_unitario = getattr(equipo, f'precio_{periodo}', 0) or 0

                        detalle.save()

                    # Calcular totales
                    alquiler.calcular_precio_total()
                    if alquiler.con_iva:
                        alquiler.iva = (alquiler.precio_total * Decimal('0.19')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                        alquiler.save(update_fields=['iva'])

                    messages.success(request, "Reserva creada exitosamente.")
                    return HttpResponseRedirect(f"{reverse('alquiler:listar_alquileres')}?alquiler_id={alquiler.id}")

            except Exception as e:
                messages.error(request, f"Error al guardar: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error en {field}: {error}")

            for f in formset:
                for field, errors in f.errors.items():
                    for error in errors:
                        messages.error(request, f"Error en equipo ({field}): {error}")
    else:
        form = AlquilerForm(
            initial={
                'fecha_inicio': timezone.now().date(),
                'fecha_fin': timezone.now().date() + timedelta(days=7),
                'con_iva': True
            },
            request=request
        )
        form.fields['numero_factura'].widget = forms.HiddenInput()
        form.initial['numero_factura'] = None
        formset = DetalleAlquilerFormSet(prefix='detalles')

    return render(request, 'reservar_alquiler.html', {
        'form': form,
        'formset': formset,
        'equipos_disponibles': equipos_disponibles
    })


@login_required
@permission_required('alquiler.change_alquiler', raise_exception=True)
def aprobar_alquiler(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)

    if alquiler.estado_alquiler in ['reservado', 'pendiente_aprobacion']:
        try:
            with transaction.atomic():
                # Cambiar estado
                alquiler.estado_alquiler = 'activo'
                alquiler.es_reserva = False
                alquiler.aprobado_por = getattr(request.user, 'nombre_usuario', str(request.user))
                alquiler.fecha_vencimiento = alquiler.fecha_fin

                # Generar número de factura si no tiene
                if not alquiler.numero_factura:
                    last = Alquiler.objects.filter(
                        es_reserva=False,
                        numero_factura__isnull=False
                    ).exclude(numero_factura='').order_by('-fecha_creacion').first()

                    last_number = 0
                    if last and last.numero_factura:
                        match = re.search(r'FACT[-]?(\d+)', last.numero_factura)
                        if match:
                            last_number = int(match.group(1))

                    # Buscar número de factura disponible
                    while True:
                        nuevo_numero = last_number + 1
                        nuevo_factura = f"FACT-{nuevo_numero:04d}"
                        if not Alquiler.objects.filter(numero_factura=nuevo_factura).exists():
                            alquiler.numero_factura = nuevo_factura
                            break
                        last_number += 1

                alquiler.save()

                # Actualizar detalles del alquiler
                for detalle in alquiler.detalles.all():
                    # Asignar precio unitario si no tiene
                    if not detalle.precio_unitario or detalle.precio_unitario == 0:
                        equipo = detalle.equipo
                        periodo = detalle.periodo_alquiler
                        detalle.precio_unitario = getattr(equipo, f'precio_{periodo}', 0) or 0

                    # Esto también recalcula precio_total y actualiza disponibilidad
                    detalle.save()

                # Recalcular totales y generar pago inicial
                alquiler.calcular_precio_total()
                crear_pago_inicial(alquiler, aprobado_por=request.user)

                messages.success(request, "Reserva aprobada y convertida en alquiler activo exitosamente.")

        except Exception as e:
            messages.error(request, f"Error al aprobar la reserva: {str(e)}")
    else:
        messages.warning(request, "Solo se pueden aprobar reservas o alquileres en estado pendiente.")

    return redirect('alquiler:listar_alquileres')


@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def series_disponibles(request, equipo_id):
    equipo = get_object_or_404(Equipo, uuid_id=equipo_id)
    series = equipo.numeros_serie_lista()
    
    return JsonResponse({
        'series': series,
        'precio_dia': float(equipo.precio_dia),
        'precio_semana': float(equipo.precio_semana or 0),
        'precio_mes': float(equipo.precio_mes or 0),
        'precio_trimestre': float(equipo.precio_trimestre or 0),
        'precio_semestre': float(equipo.precio_semestre or 0),
        'precio_anio': float(equipo.precio_anio or 0),
        'cantidad_disponible': equipo.cantidad_disponible
    })


@login_required
@permission_required('alquiler.change_alquiler', raise_exception=True)
def finalizar_alquiler(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)

    # Verifica si el alquiler ya está finalizado o cancelado
    if alquiler.estado_alquiler in ['finalizado', 'cancelado']:
        messages.warning(request, f"Este alquiler ya está {alquiler.get_estado_alquiler_display().lower()}.")
        return redirect('alquiler:listar_alquileres')

    # Verifica si ha pasado la fecha de vencimiento
    fecha_vencimiento = alquiler.fecha_vencimiento
    fecha_actual = datetime.date.today()
    
    if fecha_actual <= fecha_vencimiento:
        messages.error(request, "No se puede finalizar el alquiler antes de la fecha de vencimiento.")
        return redirect('alquiler:listar_alquileres')

    # Si la fecha de vencimiento ha pasado, se procede a finalizar el alquiler
    alquiler.estado_alquiler = 'finalizado'
    alquiler.save()

    for detalle in alquiler.detalles.all():
        equipo = detalle.equipo
        
        if detalle.numeros_serie:
            if isinstance(detalle.numeros_serie, str):
                try:
                    returned_series = json.loads(detalle.numeros_serie)
                except json.JSONDecodeError:
                    returned_series = [s.strip() for s in detalle.numeros_serie.split(',') if s.strip()]
            else: 
                returned_series = detalle.numeros_serie
            
            current_equipo_series = []
            if equipo.numero_serie:
                current_equipo_series = [s.strip() for s in equipo.numero_serie.split(',') if s.strip()]
            
            for s_num in returned_series:
                if s_num not in current_equipo_series:
                    current_equipo_series.append(s_num)
            
            equipo.numero_serie = ', '.join(sorted(current_equipo_series))
            
        equipo.save(update_fields=['numero_serie'])
        equipo.actualizar_disponibilidad()

    messages.success(request, "Alquiler finalizado exitosamente. Los equipos han sido liberados.")
    return redirect('alquiler:listar_alquileres')


@login_required
@permission_required('alquiler.change_alquiler', raise_exception=True)
def renovar_alquiler(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)

    if request.method == 'POST':
        form = RenovarAlquilerForm(request.POST)
        if form.is_valid():
            alquiler.fecha_fin = form.cleaned_data['nueva_fecha_fin']
            alquiler.renovacion = True
            alquiler.save()
            messages.success(request, "Alquiler renovado exitosamente.")
            return redirect('alquiler:listar_alquileres')
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = RenovarAlquilerForm(initial={
            'nueva_fecha_fin': alquiler.fecha_fin + timedelta(days=7),
        })

    return render(request, 'renovar_alquiler.html', {
        'form': form,
        'alquiler': alquiler,
    })


@login_required
@permission_required('alquiler.view_acta', raise_exception=True)
def generar_acta_entrega(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)    
    # Renderizar template con el contexto necesario
    html = render_to_string('acta_entrega.html', {
        'alquiler': alquiler,
        'request': request  # Pasar el request para construir URLs absolutas
    })
    
    # Crear respuesta PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="acta_entrega_{alquiler.id}.pdf"'
    
    # Convertir HTML a PDF
    result = BytesIO()
    pisa_status = pisa.CreatePDF(
        html,
        dest=response,
        encoding='UTF-8',
        link_callback=lambda uri, _: request.build_absolute_uri(uri))
    
    if pisa_status.err:
        return HttpResponse("Error al generar el PDF", status=500)
    
    return response


@login_required
@permission_required('alquiler.view_acta', raise_exception=True)
def generar_acta_devolucion(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)
    
    # Renderizar template
    html = render_to_string('acta_devolucion.html', {
        'alquiler': alquiler,
        'fecha_actual': timezone.now().date(),
        'request': request
    })
    
    # Generar PDF
    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(
        html,
        dest=pdf_buffer,
        encoding='UTF-8',
        link_callback=lambda uri, _: request.build_absolute_uri(uri)
    )
    
    if pisa_status.err:
        return HttpResponse("Error al generar el PDF", status=500)
    
    # Guardar el acta en el historial
    from django.core.files.base import ContentFile
    pdf_content = ContentFile(pdf_buffer.getvalue())
    
    acta = Acta.objects.create(
        alquiler=alquiler,
        tipo='devolucion'
    )
    acta.archivo.save(f'acta_devolucion_{alquiler.id}_{timezone.now().date()}.pdf', pdf_content)
    
    # Preparar respuesta para descarga
    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="acta_devolucion_{alquiler.id}.pdf"'
    return response

@login_required
def alertas_devoluciones_proximas():
    proximos = Alquiler.objects.filter(
        fecha_fin=timezone.now().date() + timedelta(days=1),
        estado_alquiler='activo'
    )

    for alquiler in proximos:
        send_mail(
            'Recordatorio: Devolución próxima del equipo',
            f'Hola {alquiler.cliente.nombre}, recuerda devolver el equipo {alquiler.equipo} mañana ({alquiler.fecha_fin}).',
            'no-reply@tuempresa.com',
            [alquiler.cliente.email],
            fail_silently=False,
        )


@login_required
@permission_required('alquiler.view_alquiler', raise_exception=True)
def detalle_alquiler(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)
    
    # Obtener historial de actas (usando el modelo unificado)
    historial_entregas = Acta.objects.filter(
        alquiler=alquiler, 
        tipo='entrega'
    ).order_by('-fecha_creacion')[:3]
    
    historial_devoluciones = Acta.objects.filter(
        alquiler=alquiler, 
        tipo='devolucion'
    ).order_by('-fecha_creacion')[:3]
    
    # Obtener historial de contratos
    historial_contratos = Contrato.objects.filter(
    alquiler=alquiler
    ).order_by('-fecha_contratacion')[:3]

    
    context = {
        'alquiler': alquiler,
        'historial_entregas': historial_entregas,
        'historial_devoluciones': historial_devoluciones,
        'historial_contratos': historial_contratos,
    }
    
    return render(request, 'detalle_alquiler.html', context)


@login_required
@permission_required('alquiler.view_alquiler', raise_exception=True)
def calendario_alquileres(request):
    # Obtener todos los alquileres o solo los del usuario actual
    if request.user.is_superuser:
        alquileres = Alquiler.objects.filter(estado_alquiler='activo').prefetch_related('detalles__equipo')
    else:
        # Filtra por el usuario que inició sesión
        alquileres = Alquiler.objects.filter(
            estado_alquiler='activo',
            creado_por=request.user
        ).prefetch_related('detalles__equipo')

    eventos = []

    for alquiler in alquileres:
        equipos = [f"{detalle.equipo.marca} {detalle.equipo.modelo}" for detalle in alquiler.detalles.all()]
        equipos_str = " | ".join(equipos) if equipos else "Sin equipos"

        eventos.append({
            "title": f"{equipos_str} - {alquiler.cliente.nombre} - INICIO",
            "start": alquiler.fecha_inicio.strftime("%Y-%m-%d"),
            "color": "#28a745",
            "url": f"/alquileres/{alquiler.uuid_id}/detalle/"
        })

        eventos.append({
            "title": f"{equipos_str} - {alquiler.cliente.nombre} - FIN",
            "start": alquiler.fecha_fin.strftime("%Y-%m-%d"),
            "color": "#dc3545",
            "url": f"/alquileres/{alquiler.uuid_id}/detalle/"
        })

        # Evento de aviso por vencer (3 días antes)
        fecha_aviso = alquiler.fecha_fin - timedelta(days=3)
        eventos.append({
            "title": f"{equipos_str} - {alquiler.cliente.nombre} - POR VENCER",
            "start": fecha_aviso.strftime("%Y-%m-%d"),
            "color": "#ffc107",
            "url": f"/alquileres/{alquiler.uuid_id}/detalle/"
        })

    eventos_json = json.dumps(eventos)
    return render(request, "calendario.html", {
        "eventos_json": eventos_json,
        "current_year": datetime.now().year,
        "es_superusuario": request.user.is_superuser, # Pasa esta variable al template
    })


@login_required
@permission_required('alquiler.change_alquiler', raise_exception=True)
def cancelar_alquiler(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)
    if alquiler.estado_alquiler != 'cancelado':
        alquiler.estado_alquiler = 'cancelado'
        alquiler.save()

        for detalle in alquiler.detalles.all():
            detalle.equipo.estado = 'disponible'
            detalle.equipo.save()

        messages.warning(request, "Alquiler cancelado.")
    else:
        messages.info(request, "Este alquiler ya estaba cancelado.")
    return redirect('alquiler:listar_alquileres')

@login_required
@permission_required('alquiler.add_contrato', raise_exception=True)
def crear_contrato(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)

    if hasattr(alquiler, 'contrato'):
        messages.warning(request, "Este alquiler ya tiene un contrato generado.")
        return redirect('alquiler:detalle_alquiler', id=alquiler.uuid_id)

    if not alquiler.detalles.exists():
        messages.error(request, "No hay equipos asociados a este alquiler.")
        return redirect('alquiler:detalle_alquiler', id=alquiler.uuid_id)

    # Validar que el alquiler tenga un número de factura
    if not alquiler.numero_factura:
        messages.error(request, "No se puede crear el contrato: el número de factura está vacío.")
        return redirect('alquiler:detalle_alquiler', id=alquiler.uuid_id)

    contrato = Contrato.objects.create(alquiler=alquiler)
    messages.success(request, "Contrato creado correctamente. Ahora debe ser firmado.")
    return redirect('alquiler:firmar_contrato', id=alquiler.uuid_id)


@login_required
@permission_required('alquiler.change_contrato', raise_exception=True)
def firmar_contrato(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)
    contrato = get_object_or_404(Contrato, alquiler=alquiler)

    if request.method == 'POST':
        firma_file = request.FILES.get('firma_imagen')
        firma_data = request.POST.get('firma_data')
        firma_representante_file = request.FILES.get('firma_representante_imagen')
        firma_representante_data = request.POST.get('firma_representante_data')
        print(f"Firma data recibida: {firma_data is not None}")  # Debug
        print(f"Firma representante data recibida: {firma_representante_data is not None}")  # D
        # Validación básica de firmas
        if not (firma_file or firma_data):
            messages.error(request, "Debe proporcionar la firma del arrendatario")
            return render(request, 'firmar_contrato.html', {'alquiler': alquiler, 'contrato': contrato})

        if not (firma_representante_file or firma_representante_data):
            messages.error(request, "Debe proporcionar la firma del arrendador")
            return render(request, 'firmar_contrato.html', {'alquiler': alquiler, 'contrato': contrato})

        try:
            # Procesar firma del cliente (arrendatario)
            if firma_file:
                # Redimensionar imagen antes de guardar
                img = Image.open(firma_file)
                
                # Convertir a RGBA si es PNG para mantener transparencia
                if img.format == 'PNG':
                    img = img.convert('RGBA')
                    background = Image.new('RGBA', img.size, (255, 255, 255))
                    img = Image.alpha_composite(background, img)
                    img = img.convert('RGB')
                
                # Redimensionar manteniendo relación de aspecto
                img.thumbnail((300, 150), Image.LANCZOS)
                
                # Guardar imagen optimizada
                output = BytesIO()
                img.save(output, format='PNG', quality=90)
                output.seek(0)
                
                contrato.firma_cliente.save(
                    f"firma_cliente_{alquiler.id}.png", 
                    ContentFile(output.read()), 
                    save=False
                )
                
            elif firma_data and "base64" in firma_data:
                # Procesar firma dibujada
                format, imgstr = firma_data.split(';base64,')
                ext = format.split('/')[-1]
                
                # Decodificar imagen base64
                img_data = base64.b64decode(imgstr)
                img = Image.open(BytesIO(img_data))
                
                # Crear fondo blanco para firmas transparentes
                if img.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                
                # Redimensionar
                img.thumbnail((300, 150), Image.LANCZOS)
                
                # Guardar
                output = BytesIO()
                img.save(output, format='PNG', quality=90)
                output.seek(0)
                
                contrato.firma_cliente.save(
                    f"firma_cliente_dibujada_{alquiler.id}.png",
                    ContentFile(output.read()),
                    save=False
                )

            # Procesar firma del representante (arrendador)
            if firma_representante_file:
                # Redimensionar imagen antes de guardar
                img = Image.open(firma_representante_file)
                
                # Manejar transparencia para PNG
                if img.format == 'PNG':
                    img = img.convert('RGBA')
                    background = Image.new('RGBA', img.size, (255, 255, 255))
                    img = Image.alpha_composite(background, img)
                    img = img.convert('RGB')
                
                # Redimensionar
                img.thumbnail((300, 150), Image.LANCZOS)
                
                # Guardar
                output = BytesIO()
                img.save(output, format='PNG', quality=90)
                output.seek(0)
                
                contrato.firma_representante.save(
                    f"firma_representante_{alquiler.id}.png",
                    ContentFile(output.read()),
                    save=False
                )
                
            elif firma_representante_data and "base64" in firma_representante_data:
                # Procesar firma dibujada
                format, imgstr = firma_representante_data.split(';base64,')
                ext = format.split('/')[-1]
                
                # Decodificar imagen base64
                img_data = base64.b64decode(imgstr)
                img = Image.open(BytesIO(img_data))
                
                # Crear fondo blanco para firmas transparentes
                if img.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                
                # Redimensionar
                img.thumbnail((300, 150), Image.LANCZOS)
                
                # Guardar
                output = BytesIO()
                img.save(output, format='PNG', quality=90)
                output.seek(0)
                
                contrato.firma_representante.save(
                    f"firma_representante_dibujada_{alquiler.id}.png",
                    ContentFile(output.read()),
                    save=False
                )

            # Actualizar fecha de firma
            contrato.fecha_firma = timezone.now().date()
            contrato.save()

            # Generar documento PDF con las firmas
            if contrato.generar_documento_contrato():
                messages.success(request, "¡Contrato firmado y generado correctamente!")
                return redirect('alquiler:detalle_alquiler', id=alquiler.uuid_id)
            else:
                messages.error(request, "Error al generar el documento PDF del contrato")
                return render(request, 'firmar_contrato.html', {'alquiler': alquiler, 'contrato': contrato})

        except Exception as e:
            messages.error(request, f"Error al procesar las firmas: {str(e)}")
            return render(request, 'firmar_contrato.html', {'alquiler': alquiler, 'contrato': contrato})

    # GET request - mostrar formulario de firma
    return render(request, 'firmar_contrato.html', {
        'alquiler': alquiler,
        'contrato': contrato
    })


@login_required
@permission_required('alquiler.change_contrato', raise_exception=True)
def renovar_contrato(request, id):
    try:
        alquiler_original = get_object_or_404(Alquiler, uuid_id=id)
    except Http404:
        messages.error(request, f"El alquiler con ID '{id}' no fue encontrado. Por favor, verifique la URL o si el alquiler existe.")
        return redirect('alquiler:listar_alquileres') 
    except Exception as e:
        messages.error(request, f"Ocurrió un error inesperado al buscar el alquiler. Por favor, inténtelo de nuevo.")
        return redirect('alquiler:listar_alquileres')

    if not hasattr(alquiler_original, 'contrato') or not alquiler_original.contrato:
        messages.error(request, "El alquiler original no tiene contrato asociado y no puede ser renovado.")
        return redirect('alquiler:detalle_alquiler', id=alquiler_original.uuid_id)

    if alquiler_original.estado_alquiler not in ['activo', 'finalizado']:
        messages.error(request, f"Solo se pueden renovar alquileres activos o finalizados. Estado actual: '{alquiler_original.estado_alquiler}'.")
        return redirect('alquiler:detalle_alquiler', id=alquiler_original.uuid_id)

    if request.method == 'POST':
        form = AlquilerForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    nuevo_alquiler = form.save(commit=False)
                    nuevo_alquiler.estado_alquiler = 'activo'
                    nuevo_alquiler.cliente = alquiler_original.cliente
                    nuevo_alquiler.renovacion = True
                    nuevo_alquiler.es_reserva = False

                    user = request.user
                    nombre_aprobador = f"{getattr(user, 'nombre', '')} {getattr(user, 'apellido', '')}".strip()
                    if not nombre_aprobador:
                        nombre_aprobador = getattr(user, 'nombre_usuario', '') or user.username
                    nuevo_alquiler.aprobado_por = nombre_aprobador

                    nuevo_alquiler.numero_factura = form.cleaned_data.get('numero_factura')
                    if not nuevo_alquiler.numero_factura:
                        raise ValidationError("Debe ingresar un número de factura para la renovación.")
                    
                    nuevo_alquiler.save()

                    for detalle in alquiler_original.detalles.all():
                        DetalleAlquiler.objects.create(
                            alquiler=nuevo_alquiler,
                            equipo=detalle.equipo,
                            numeros_serie=detalle.numeros_serie,
                            periodo_alquiler=detalle.periodo_alquiler,
                            cantidad=detalle.cantidad,
                            precio_unitario=detalle.precio_unitario
                        )
                        detalle.equipo.actualizar_disponibilidad()
                    
                    contrato_original = alquiler_original.contrato
                    if not contrato_original:
                        raise Exception("El contrato original no pudo ser clonado porque es nulo.")

                    nuevo_contrato = Contrato.objects.create(
                        alquiler=nuevo_alquiler,
                        terminos_contrato=contrato_original.terminos_contrato,
                        fecha_contratacion=timezone.now().date()
                    )
                    nuevo_contrato.generar_documento_contrato()

                    if alquiler_original.estado_alquiler == 'activo':
                        alquiler_original.estado_alquiler = 'finalizado'
                        alquiler_original.save()

                    messages.success(request, f"Contrato de renovación # {nuevo_alquiler.numero_factura} creado correctamente. Ahora debe ser firmado.")
                    return redirect('alquiler:firmar_contrato', id=nuevo_alquiler.uuid_id)

            except ValidationError as ve:
                messages.error(request, f"Error de validación al renovar: {str(ve)}")
            except Exception as e:
                messages.error(request, f"Ocurrió un error inesperado al renovar el contrato: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error en el campo '{form[field].label}': {error}")
    else:
        fecha_inicio_sugerida = alquiler_original.fecha_fin
        
        if fecha_inicio_sugerida < timezone.now().date():
            fecha_inicio_sugerida = timezone.now().date()

        fecha_fin_sugerida = fecha_inicio_sugerida + timedelta(days=30)

        form = AlquilerForm(initial={
            'fecha_inicio': fecha_inicio_sugerida,
            'fecha_fin': fecha_fin_sugerida,
            'observaciones': f"",
            'renovacion': True
        })
        
        form.fields['cliente'].widget = forms.HiddenInput()
        form.fields['cliente'].required = False

        form.fields['numero_factura'].required = True
        form.fields['numero_factura'].widget = forms.TextInput(attrs={'class': 'form-control', 'required': 'required'})

    context = {
        'form': form,
        'alquiler_anterior': alquiler_original,
        'contrato_original': alquiler_original.contrato,
        'detalles_originales': alquiler_original.detalles.all(),
        'cliente_original': alquiler_original.cliente
    }

    return render(request, 'renovar_contrato.html', context)


@login_required
@permission_required('alquiler.delete_alquiler', raise_exception=True)
def eliminar_alquiler(request, id):
    alquiler = get_object_or_404(Alquiler, uuid_id=id)

    if request.method == 'POST':
        alquiler.delete()
        messages.success(request, "Alquiler eliminado correctamente.")
        return redirect('alquiler:listar_alquileres')

    return render(request, 'eliminar_alquiler.html', {'alquiler': alquiler})