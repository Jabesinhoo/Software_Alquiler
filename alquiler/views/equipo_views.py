from django.shortcuts import render, redirect, get_object_or_404
from alquiler.models import Equipo, Alquiler, Cliente, Pago
from alquiler.models import UnidadEquipo
from alquiler.forms.equipo_forms import EquipoForm
import csv
from django.db import models
from django.http import JsonResponse
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.db.models import Count, Max
from ..models import Equipo, Alquiler, FotoEquipo, DetalleAlquiler
from ..forms import EquipoForm, FotoEquipoForm, EquipoEditForm
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.views.decorators.http import require_POST
from django.forms.models import inlineformset_factory
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render
import json
import xlsxwriter
import io
import uuid
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
from django.db.models import Sum, Count, Avg, Max, F, Q, ExpressionWrapper, FloatField, DurationField, DecimalField
from django.db.models.functions import ExtractMonth, ExtractYear, TruncMonth
from datetime import datetime
from decimal import Decimal
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from email.mime.image import MIMEImage
import os
import traceback
from PIL import Image  
from io import BytesIO
from itertools import groupby
from django.db.models import Exists, OuterRef


@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def listar_equipos(request):
    equipos = Equipo.objects.all()
    form = EquipoForm() if request.user.is_staff else None
    return render(request, 'lista.html', {'equipos': equipos, 'form': form})


@login_required
@permission_required('alquiler.add_equipo', raise_exception=True)
def crear_equipo(request):
    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                equipo = form.save()

                # Crear instancias de UnidadEquipo a partir del campo "seriales"
                seriales = request.POST.get('seriales', '')
                for linea in seriales.splitlines():
                    linea = linea.strip()
                    if linea:
                        UnidadEquipo.objects.create(equipo=equipo, numero_serie=linea)

                messages.success(request, f'Equipo {equipo.marca} {equipo.modelo} creado exitosamente!')
                return redirect('alquiler:detalle_equipo', id=equipo.uuid_id)

            except Exception as e:
                messages.error(request, f'Error al guardar el equipo: {str(e)}')
        else:
            print("[DEBUG] Formulario inválido:", form.errors)
    else:
        form = EquipoForm()

    return render(request, 'crear.html', {
        'form': form,
        'titulo': 'Crear Nuevo Equipo'
    })


@login_required
@permission_required('alquiler.change_equipo', raise_exception=True)
def editar_equipo(request, id):
    equipo = get_object_or_404(Equipo, uuid_id=id)

    FotoEquipoFormSet = inlineformset_factory(
        Equipo,
        FotoEquipo,
        form=FotoEquipoForm,
        extra=1,
        can_delete=True
    )

    if request.method == 'POST':
        form = EquipoEditForm(data=request.POST, files=request.FILES, instance=equipo)
        formset = FotoEquipoFormSet(data=request.POST, files=request.FILES, instance=equipo)

        if form.is_valid() and formset.is_valid():
            try:
                # Verificar que haya al menos una foto final
                fotos_existentes = equipo.fotos.all()
                fotos_a_eliminar = []
                for form_foto in formset.forms:
                    if form_foto.cleaned_data.get('DELETE') and form_foto.instance.pk:
                        fotos_a_eliminar.append(form_foto.instance.pk)

                fotos_restantes = fotos_existentes.exclude(pk__in=fotos_a_eliminar).count()
                nuevas_fotos_formset = sum(1 for form_foto in formset.forms 
                                           if form_foto.cleaned_data.get('foto') and not form_foto.cleaned_data.get('DELETE'))
                nuevas_fotos_adicionales = len(request.FILES.getlist('nuevas_fotos[]'))

                total_fotos_finales = fotos_restantes + nuevas_fotos_formset + nuevas_fotos_adicionales
                if total_fotos_finales == 0:
                    form.add_error(None, "El equipo debe tener al menos una foto.")
                else:
                    equipo = form.save()
                    formset.save()

                    # Procesar fotos adicionales
                    nuevas_fotos = request.FILES.getlist('nuevas_fotos[]')
                    for foto in nuevas_fotos:
                        FotoEquipo.objects.create(
                            equipo=equipo,
                            foto=foto,
                            es_principal=False,
                            descripcion=f"Foto del equipo {equipo.marca} {equipo.modelo}"
                        )

                    # Validar foto principal
                    fotos_principales = equipo.fotos.filter(es_principal=True)
                    if fotos_principales.count() > 1:
                        ultima = fotos_principales.order_by('-id').first()
                        equipo.fotos.exclude(id=ultima.id).update(es_principal=False)
                    elif fotos_principales.count() == 0 and equipo.fotos.exists():
                        primera = equipo.fotos.first()
                        primera.es_principal = True
                        primera.save()

                    messages.success(request, f'Equipo {equipo} actualizado exitosamente!')
                    return redirect('alquiler:detalle_equipo', id=equipo.uuid_id)

            except Exception as e:
                messages.error(request, f'Error al guardar los cambios: {str(e)}')
        else:
            print("[DEBUG] Errores form:", form.errors)
            print("[DEBUG] Errores formset:", formset.errors)

    else:
        form = EquipoEditForm(instance=equipo)
        formset = FotoEquipoFormSet(instance=equipo)

    return render(request, 'editar.html', {
        'form': form,
        'formset': formset,
        'equipo': equipo,
        'titulo': f'Editar {equipo.marca} {equipo.modelo}'
    })


@login_required
@permission_required('alquiler.delete_equipo', raise_exception=True)
@require_POST
def eliminar_equipo(request, pk):
    equipo = get_object_or_404(Equipo, uuid_id=pk)
    try:
        equipo.fotos.all().delete()
        equipo.delete()
        messages.success(request, f'El equipo {equipo.marca} {equipo.modelo} ha sido eliminado correctamente.')
    except Exception as e:
        messages.error(request, f'Error al eliminar el equipo: {str(e)}')
    return redirect('alquiler:listar_equipos')


@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def detalle_equipo(request, id):
    equipo = get_object_or_404(Equipo, uuid_id=id)
    historial = Alquiler.objects.filter(detalles__equipo=equipo).order_by('-fecha_inicio')[:5]
    
    # Obtener equipos similares (misma categoría o etiqueta)
    equipos_similares = Equipo.objects.filter(
        estado=equipo.estado
    )
    
    if 'quick-view' in request.path:
        return render(request, 'quick_view.html', {
            'equipo': equipo,
            'historial': historial
        })
    
    return render(request, 'detalle.html', {
        'equipo': equipo,
        'historial': historial,
        'equipos_similares': equipos_similares
    })


@login_required
def equipos_disponibles(request):
    equipos = Equipo.objects.filter(estado='disponible')
    return render(request, 'lista.html', {'equipos': equipos})

@login_required
@permission_required('alquiler.change_equipo', raise_exception=True)
def cambiar_estado_equipo(request, id, nuevo_estado):
    equipo = get_object_or_404(Equipo, uuid_id=id)
    equipo.estado = nuevo_estado
    equipo.save()
    return redirect('alquiler:listar_equipos')

@login_required
def equipos_por_estado(request, estado):
    equipos = Equipo.objects.filter(estado=estado)
    return render(request, 'lista.html', {'equipos': equipos})

@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def pagos_pendientes_admin(request):
    pagos = Pago.objects.filter(estado_pago='pendiente').select_related('alquiler', 'alquiler__cliente')
    return render(request, 'pagos_pendientes.html', {'pagos': pagos})

@login_required
@permission_required('alquiler.view_reportes', raise_exception=True)
def dashboard_admin(request):
    # 1. Estadísticas básicas
    total_equipos = Equipo.objects.count()
    total_alquilados = Equipo.objects.filter(estado='alquilado').count()
    pagos_pendientes = Pago.objects.filter(estado_pago='pendiente').count()
    clientes_verificados = Cliente.objects.filter(estado_verificacion='verificado').count()
    
    # 2. Cálculos porcentuales
    total_clientes = Cliente.objects.count()
    porcentaje_alquilados = (total_alquilados / total_equipos * 100) if total_equipos > 0 else 0
    porcentaje_verificados = (clientes_verificados / total_clientes * 100) if total_clientes > 0 else 0
    
    # 3. Datos para el gráfico de estado de equipos
    estados_equipos = [
        {'nombre': 'Disponible', 'cantidad': Equipo.objects.filter(estado='disponible').count(), 'color': '#4e73df'},
        {'nombre': 'Alquilado', 'cantidad': total_alquilados, 'color': '#1cc88a'},
        {'nombre': 'Mantenimiento', 'cantidad': Equipo.objects.filter(estado='mantenimiento').count(), 'color': '#36b9cc'},
        {'nombre': 'Reservado', 'cantidad': Equipo.objects.filter(estado='reservado').count(), 'color': '#f6c23e'}
    ]
    
    # 4. Próximos vencimientos (7 días)
    fecha_limite = timezone.now().date() + timedelta(days=7)
    proximos_vencimientos = Alquiler.objects.filter(
        fecha_fin__lte=fecha_limite,
        fecha_fin__gte=timezone.now().date(),
        estado_alquiler='activo'
    ).select_related('cliente').prefetch_related('detalles', 'detalles__equipo').annotate(
        dias_restantes=ExpressionWrapper(
            F('fecha_fin') - timezone.now().date(),
            output_field=DurationField()
        )
    ).order_by('fecha_fin')[:5]
    
    # 5. Últimos alquileres registrados
    ultimos_alquileres = Alquiler.objects.select_related('cliente')\
        .prefetch_related('detalles', 'detalles__equipo')\
        .order_by('-fecha_inicio')[:5]
    
    # 6. Equipos más alquilados (top 5)
    equipos_populares = Equipo.objects.annotate(
        total_alquileres=Count('detallealquiler')
    ).order_by('-total_alquileres')[:5]
    
    # 7. Ingresos mensuales (últimos 6 meses)
    meses = []
    ingresos_mensuales = []
    for i in range(5, -1, -1):
        mes = timezone.now().date() - timedelta(days=30*i)
        meses.append(mes.strftime('%b %Y'))
        
        inicio_mes = mes.replace(day=1)
        fin_mes = (inicio_mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        total = Pago.objects.filter(
            fecha_pago__gte=inicio_mes,
            fecha_pago__lte=fin_mes,
            estado_pago='pagado'
        ).aggregate(total=Sum('monto'))['total'] or 0
        
        ingresos_mensuales.append(float(total))
    
    # 8. Clientes con más alquileres - CORRECCIÓN AQUÍ
    clientes_frecuentes = Cliente.objects.annotate(
        total_alquileres=Count('alquileres'),
        monto_total=Sum('alquileres__precio_total')
    ).order_by('-total_alquileres')[:5]
    
    # 9. Equipos que generan más ingresos - CORRECCIÓN AQUÍ
    equipos_rentables = Equipo.objects.annotate(
        ingresos_totales=Sum('detallealquiler__precio_total')
    ).order_by('-ingresos_totales')[:5]
    
    # 10. Pagos pendientes con mayor monto
    pagos_pendientes_importantes = Pago.objects.filter(
        estado_pago='pendiente'
    ).order_by('-monto')[:5]
    
    return render(request, 'dashboard.html', {
        'total_equipos': total_equipos,
        'total_alquilados': total_alquilados,
        'pagos_pendientes': pagos_pendientes,
        'clientes_verificados': clientes_verificados,
        'porcentaje_alquilados': porcentaje_alquilados,
        'porcentaje_verificados': porcentaje_verificados,
        'estados_equipos': estados_equipos,
        'proximos_vencimientos': proximos_vencimientos,
        'ultimos_alquileres': ultimos_alquileres,
        'equipos_populares': equipos_populares,
    })

@login_required
@permission_required('alquiler.change_equipo', raise_exception=True)
def actualizar_estados_masivo(request):
    if request.method == 'POST':
        ids_equipos_raw = request.POST.getlist('ids_equipos')
        # Si la entrada es un solo string separado por comas, divídelo
        if len(ids_equipos_raw) == 1 and ',' in ids_equipos_raw[0]:
            ids_equipos_raw = ids_equipos_raw[0].split(',')
        
        # Convertir los strings de UUID a objetos UUID
        valid_uuids = []
        for item_id in ids_equipos_raw:
            try:
                valid_uuids.append(uuid.UUID(item_id.strip()))
            except ValueError:
                # Opcional: Manejar IDs que no son UUIDs válidos (por ejemplo, loguear un error)
                # Por ahora, simplemente los omitimos
                continue 

        if not valid_uuids:
            messages.error(request, "Debes seleccionar al menos un equipo válido para actualizar.")
            return redirect('alquiler:actualizar_estados_masivo')
        
        nuevo_estado = request.POST.get('nuevo_estado')
        
        if not nuevo_estado:
            messages.error(request, "Debes seleccionar un estado válido")
            return redirect('alquiler:actualizar_estados_masivo')
        
        # Validar estado
        estados_validos = [estado[0] for estado in Equipo.ESTADOS]
        if nuevo_estado not in estados_validos:
            messages.error(request, "Estado seleccionado no válido")
            return redirect('alquiler:actualizar_estados_masivo')
        
        # Obtener equipos sin alquileres activos
        equipos_permitidos = Equipo.objects.filter(
            uuid_id__in=valid_uuids # Usamos los UUIDs validados
        ).exclude(
            detallealquiler__alquiler__estado_alquiler='activo'
        ).distinct()

        # Calcular equipos con alquileres activos (solo una vez y usando uuid_id)
        equipos_con_alquiler = Equipo.objects.filter(
            uuid_id__in=valid_uuids, # Usamos los UUIDs validados
            detallealquiler__alquiler__estado_alquiler='activo'
        ).distinct().count()

        # Actualizar solo los permitidos
        count = equipos_permitidos.update(estado=nuevo_estado)
        
        if count > 0:
            messages.success(request, f"Se actualizaron {count} equipos correctamente a estado {dict(Equipo.ESTADOS)[nuevo_estado]}")
        if equipos_con_alquiler > 0:
            messages.warning(request, f"{equipos_con_alquiler} equipos no se actualizaron porque tienen alquileres activos")
        
        return redirect('alquiler:listar_equipos')
    
    # Obtener todos los equipos con información de alquileres activos
    equipos = Equipo.objects.annotate(
        tiene_alquiler_activo=Exists(
            DetalleAlquiler.objects.filter(
                equipo=OuterRef('pk'), # 'pk' se refiere al primary key del Equipo, que sigue siendo el id entero
                alquiler__estado_alquiler='activo'
            )
        )
    ).order_by('marca', 'modelo')
    
    estados = Equipo.ESTADOS
    
    return render(request, 'actualizar_masivo.html', {
        'equipos': equipos,
        'estados': estados
    })


@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def exportar_equipos_csv(request):
    equipos = Equipo.objects.all()
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="equipos.csv"'

    writer = csv.writer(response)
    writer.writerow(['Marca', 'Modelo', 'Serie', 'Estado'])

    for eq in equipos:
        writer.writerow([eq.marca, eq.modelo, eq.numero_serie, eq.estado])

    return response


@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def historial_equipo(request, id):
    equipo = get_object_or_404(Equipo, uuid_id=id)
    historial = equipo.historial_alquileres()
    return render(request, 'historial_equipo.html', {
        'equipo': equipo,
        'historial': historial
    })

@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def proxima_disponibilidad(request, id):
    equipo = get_object_or_404(Equipo, uuid_id=id)
    fecha_disponible = equipo.proxima_fecha_disponible()
    return render(request, 'proxima_disponibilidad.html', {
        'equipo': equipo,
        'fecha_disponible': fecha_disponible
    })

@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def exportar_equipos_json(request):
    equipos = Equipo.objects.all()
    data = [equipo.exportar_informacion() for equipo in equipos]
    return JsonResponse({'equipos': data}, safe=False)

@login_required
def enviar_alertas_vencimiento():
    hoy = timezone.now().date()
    fecha_limite = hoy + timedelta(days=7)

    # Obtener alquileres próximos a vencer
    alquileres_por_vencer = Alquiler.objects.filter(
    fecha_fin__range=[hoy, fecha_limite],
    estado_alquiler='activo'
    ).select_related('cliente').prefetch_related('detalles__equipo').order_by('cliente', 'numero_factura')


    if not alquileres_por_vencer.exists():
        print(f"📭 No hay alquileres por vencer en los próximos 7 días ({hoy} - {fecha_limite})")
        return

    sent_count = 0
    error_count = 0

    # Agrupar por cliente y número de factura
    grouped_alquileres = groupby(alquileres_por_vencer, key=lambda x: (x.cliente, x.numero_factura))

    for (cliente, factura), alquileres in grouped_alquileres:
        try:
            alquileres_list = list(alquileres)
            primer_alquiler = alquileres_list[0]
            dias_restantes = (primer_alquiler.fecha_fin - hoy).days
            equipos = []
            for alq in alquileres_list:
                for detalle in alq.detalles.all():
                    equipos.append(detalle.equipo)


            # Determinar tipo de notificación
            if dias_restantes <= 3:
                tipo_notificacion = "terminacion"
                notificacion_legal = (
                    "Notificación Terminación de contrato: "
                    "En caso de incumplimiento de la entrega de los equipos tecnológicos en la fecha pactada por las partes del presente contrato, "
                    "se causarán intereses moratorios a partir del día siguiente de la fecha pactada por el valor más alto permitido por la "
                    "Superintendencia Financiera."
                )
            else:
                tipo_notificacion = "renovacion"
                notificacion_legal = (
                    "Notificación Renovación de contrato: "
                    "En atención al cumplimiento de las obligaciones pactadas en el contrato vigente, y conforme a lo establecido en las cláusulas del mismo, "
                    "nos permitimos informar que dicho contrato será renovado automáticamente por un nuevo período, bajo las mismas condiciones, "
                    "salvo pacto en contrario por las partes."
                )

            # Buscar logo de la empresa
            logo_path = None
            possible_paths = [
                os.path.join(settings.MEDIA_ROOT, 'tecnonacho.png'),
                os.path.join(settings.BASE_DIR, 'alquiler', 'static', 'media', 'tecnonacho.png'),
                os.path.join(settings.STATIC_ROOT, 'media', 'tecnonacho.png')
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    logo_path = path
                    break

            # Preparar contexto para el template
            contexto = {
                'nombre_cliente': cliente.nombre,
                'numero_factura': factura,
                'fecha_inicio': primer_alquiler.fecha_inicio.strftime("%d/%m/%Y"),
                'fecha_fin': primer_alquiler.fecha_fin.strftime("%d/%m/%Y"),
                'dias_restantes': dias_restantes,
                'equipos': equipos,
                'cantidad_equipos': len(equipos),
                'precio_total': sum(alq.precio_total for alq in alquileres_list),
                'tipo_notificacion': tipo_notificacion,
                'notificacion_legal': notificacion_legal,
                'logo_empresa': 'cid:logo_tecnonacho',
            }

            # Renderizar contenido del email
            html_content = render_to_string('alerta_vencimiento.html', contexto)
            text_content = strip_tags(html_content)

            # Configurar email con valores por defecto seguros
            email_config = {
                'subject': f'Alquiler #{factura} por vencer en {dias_restantes} día(s)',
                'body': text_content,
                'from_email': getattr(settings, 'DEFAULT_FROM_EMAIL', 'notificaciones@tecnonacho.com'),
                'to': [cliente.email],
            }
            
            # Añadir reply_to si está configurado
            if hasattr(settings, 'EMAIL_REPLY_TO'):
                email_config['reply_to'] = [settings.EMAIL_REPLY_TO]

            email = EmailMultiAlternatives(**email_config)
            email.attach_alternative(html_content, "text/html")

            # Adjuntar logo de la empresa
            if logo_path:
                try:
                    with open(logo_path, 'rb') as logo_file:
                        img = Image.open(logo_file)
                        img.thumbnail((300, 300))
                        
                        img_byte_arr = BytesIO()
                        img.save(img_byte_arr, format='PNG')
                        img_byte_arr.seek(0)
                        
                        logo = MIMEImage(img_byte_arr.read())
                        logo.add_header('Content-ID', '<logo_tecnonacho>')
                        logo.add_header('Content-Disposition', 'inline', filename='logo_tecnonacho.png')
                        email.attach(logo)
                except Exception as img_error:
                    print(f"⚠️ Error procesando logo: {img_error}")
                    # Fallback sin redimensionar
                    with open(logo_path, 'rb') as logo_file:
                        logo = MIMEImage(logo_file.read())
                        logo.add_header('Content-ID', '<logo_tecnonacho>')
                        email.attach(logo)

            # Adjuntar imágenes de los equipos (máximo 3)
            imagenes_adjuntas = []
            for i, equipo in enumerate(equipos[:3]):
                if hasattr(equipo, 'obtener_foto_principal_path'):
                    foto_path = equipo.obtener_foto_principal_path()
                    if foto_path and os.path.exists(foto_path):
                        try:
                            with open(foto_path, 'rb') as img_file:
                                img = MIMEImage(img_file.read())
                                cid = f'equipo_{i}'
                                img.add_header('Content-ID', f'<{cid}>')
                                img.add_header('Content-Disposition', 'inline', 
                                            filename=f'equipo_{i}_{os.path.basename(foto_path)}')
                                email.attach(img)
                                imagenes_adjuntas.append(f'cid:{cid}')
                        except Exception as foto_error:
                            print(f"⚠️ Error adjuntando foto del equipo {equipo.id}: {foto_error}")

            # Actualizar contexto con las imágenes adjuntas
            contexto['imagenes_equipo'] = imagenes_adjuntas

            # Enviar email
            email.send(fail_silently=False)
            sent_count += 1
            print(f"✅ Alerta enviada a: {cliente.email} (Factura: {factura})")

        except Exception as e:
            error_count += 1
            print(f"❌ Error al enviar a {cliente.email}: {str(e)}")
            traceback.print_exc()

    print(f"\n📤 Resumen: {sent_count} correos enviados, {error_count} errores")


@login_required
@permission_required('alquiler.send_notifications', raise_exception=True)
def ejecutar_alertas_vencimiento(request):
    enviar_alertas_vencimiento()
    messages.success(request, "Se han procesado las alertas de vencimiento (7 días antes).")
    return redirect('alquiler:dashboard_admin')  # cambia al nombre de tu vista de inicio



@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def equipos_mas_alquilados(request):
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    marca = request.GET.get('tipo_equipo')
    agrupar_por = request.GET.get('agrupar_por', 'equipo')

    # INICIALIZACIÓN DE LA VARIABLE 'filtros_alquiler'
    # Esto asegura que la variable siempre exista, incluso si no se agrupa por mes.
    filtros_alquiler = Q(es_reserva=False) | Q(estado_alquiler__in=['activo', 'finalizado'])
    if fecha_inicio and fecha_fin:
        filtros_alquiler &= Q(fecha_inicio__gte=fecha_inicio, fecha_fin__lte=fecha_fin)


    # Filtros para la consulta principal de equipos
    filtros_equipos = Q(detallealquiler__alquiler__estado_alquiler__in=['activo', 'finalizado'])

    if fecha_inicio and fecha_fin:
        filtros_equipos &= (
            Q(detallealquiler__alquiler__fecha_inicio__date__gte=fecha_inicio) &
            Q(detallealquiler__alquiler__fecha_inicio__date__lte=fecha_fin)
        )
    if marca:
        filtros_equipos &= Q(marca__iexact=marca)

    # Lógica para agrupar por mes
    if agrupar_por == 'mes':
        return estadisticas_por_mes(request, filtros_alquiler)

    equipos = (
        Equipo.objects.annotate(
            total_alquileres=Count('detallealquiler', filter=filtros_equipos),
            ingresos_generados=Coalesce(Sum(F('detallealquiler__precio_unitario') * F('detallealquiler__cantidad'), filter=filtros_equipos), Decimal('0.00')),
            precio_promedio=Coalesce(Avg('detallealquiler__precio_unitario', filter=filtros_equipos), Decimal('0.00')),
            ultimo_alquiler_fecha=Max('detallealquiler__alquiler__fecha_inicio', filter=filtros_equipos)
        ).filter(total_alquileres__gt=0).order_by('-total_alquileres')[:10]
    )


    # Agregar datos adicionales para cada equipo (clientes frecuentes y último alquiler)
    for equipo in equipos:
        clientes_frecuentes_query = DetalleAlquiler.objects.filter(equipo=equipo)
        if fecha_inicio and fecha_fin:
            clientes_frecuentes_query = clientes_frecuentes_query.filter(
                alquiler__fecha_inicio__gte=fecha_inicio,
                alquiler__fecha_fin__lte=fecha_fin
            )
        clientes = (
            clientes_frecuentes_query
            .values('alquiler__cliente__id', 'alquiler__cliente__nombre')
            .annotate(total=Count('alquiler__cliente'))
            .order_by('-total')[:3]
        )
        equipo.clientes_frecuentes = [c['alquiler__cliente__nombre'] for c in clientes]

        equipo.ultimo_alquiler = (
            DetalleAlquiler.objects
            .filter(equipo=equipo)
            .select_related('alquiler', 'alquiler__cliente')
            .order_by('-alquiler__fecha_inicio')
            .first()
        )

        # Protección: asegurar que `cantidad_disponible` y `cantidad_total` existan
        equipo.cantidad_total = getattr(equipo, 'cantidad_total', 1)
        equipo.cantidad_disponible = equipo.cantidad_total - equipo.total_alquileres

    total_equipos = Equipo.objects.count()
    total_alquileres = Alquiler.objects.filter(filtros_alquiler).count()
    total_clientes = Cliente.objects.filter(alquileres__in=Alquiler.objects.filter(filtros_alquiler)).distinct().count()
    ingresos_totales = Alquiler.objects.filter(filtros_alquiler).aggregate(
        total=Sum('precio_total')
    )['total'] or Decimal('0.00')

    marcas = Equipo.objects.values_list('marca', flat=True).distinct().order_by('marca')

    labels = [f"{e.marca} {e.modelo}" for e in equipos]
    datos_alquileres = [e.total_alquileres for e in equipos]
    datos_ingresos = [float(e.ingresos_generados) for e in equipos]

    if 'export' in request.GET:
        if request.GET['export'] == 'excel':
            return exportar_a_excel(request, equipos, labels, datos_alquileres, datos_ingresos)

        elif request.GET['export'] == 'pdf':
            return exportar_a_pdf(request, equipos, labels, datos_alquileres, datos_ingresos,
                      total_equipos, total_alquileres, total_clientes, ingresos_totales)


    return render(request, 'estadisticas.html', {
        'labels': json.dumps(labels),
        'datos': json.dumps(datos_alquileres),
        'ingresos_equipos': json.dumps(datos_ingresos),
        'equipos': equipos,
        'total_equipos': total_equipos,
        'total_alquileres': total_alquileres,
        'total_clientes': total_clientes,
        'ingresos_totales': ingresos_totales,
        'marcas': marcas,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'marca_seleccionada': marca,
        'agrupar_por': agrupar_por, 
    })


@login_required
@permission_required('alquiler.send_notifications', raise_exception=True)
def ejecutar_alertas_vencimiento(request):
    enviar_alertas_vencimiento()
    messages.success(request, "Se han procesado las alertas de vencimiento (7 días antes).")
    return redirect('alquiler:dashboard_admin')  # cambia al nombre de tu vista de inicio


@login_required
@permission_required('alquiler.view_equipo', raise_exception=True)
def equipos_mas_alquilados(request):
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    marca = request.GET.get('tipo_equipo')
    agrupar_por = request.GET.get('agrupar_por', 'equipo')

    # Se inicializa filtros_alquiler para evitar UnboundLocalError
    filtros_alquiler = Q(es_reserva=False) | Q(estado_alquiler__in=['activo', 'finalizado'])
    if fecha_inicio and fecha_fin:
        filtros_alquiler &= Q(fecha_inicio__date__gte=fecha_inicio, fecha_fin__date__lte=fecha_fin)


    # Filtros para la consulta principal de equipos
    filtros_equipos = Q(detallealquiler__alquiler__estado_alquiler__in=['activo', 'finalizado'])
    if fecha_inicio and fecha_fin:
        filtros_equipos &= (
            Q(detallealquiler__alquiler__fecha_inicio__date__gte=fecha_inicio) &
            Q(detallealquiler__alquiler__fecha_inicio__date__lte=fecha_fin)
        )
    if marca:
        filtros_equipos &= Q(marca__iexact=marca)

    # Lógica para agrupar por mes
    if agrupar_por == 'mes':
        return estadisticas_por_mes(request, filtros_alquiler)

    equipos = (
        Equipo.objects.annotate(
            # Corregido: Contar detalles para el número de alquileres
            total_alquileres=Count('detallealquiler', filter=filtros_equipos),
            # Corregido: Sumar el precio_unitario * cantidad
            ingresos_generados=Coalesce(Sum(F('detallealquiler__precio_unitario') * F('detallealquiler__cantidad'), filter=filtros_equipos), Decimal('0.00')),
            # Corregido: Promedio por precio_unitario
            precio_promedio=Coalesce(Avg('detallealquiler__precio_unitario', filter=filtros_equipos), Decimal('0.00')),
            ultimo_alquiler_fecha=Max('detallealquiler__alquiler__fecha_inicio', filter=filtros_equipos)
        ).filter(total_alquileres__gt=0).order_by('-total_alquileres')[:10]
    )

    # Agregar datos adicionales para cada equipo (clientes frecuentes y último alquiler)
    for equipo in equipos:
        clientes_frecuentes_query = DetalleAlquiler.objects.filter(equipo=equipo)
        if fecha_inicio and fecha_fin:
            clientes_frecuentes_query = clientes_frecuentes_query.filter(
                alquiler__fecha_inicio__gte=fecha_inicio,
                alquiler__fecha_fin__lte=fecha_fin
            )
        clientes = (
            clientes_frecuentes_query
            .values('alquiler__cliente__id', 'alquiler__cliente__nombre')
            .annotate(total=Count('alquiler__cliente'))
            .order_by('-total')[:3]
        )
        equipo.clientes_frecuentes = [c['alquiler__cliente__nombre'] for c in clientes]

        equipo.ultimo_alquiler = (
            DetalleAlquiler.objects
            .filter(equipo=equipo)
            .select_related('alquiler', 'alquiler__cliente')
            .order_by('-alquiler__fecha_inicio')
            .first()
        )

        equipo.cantidad_total = getattr(equipo, 'cantidad_total', 1)
        equipo.cantidad_disponible = equipo.cantidad_total - equipo.total_alquileres

    total_equipos = Equipo.objects.count()
    total_alquileres = sum(e.total_alquileres for e in equipos)
    total_clientes = Cliente.objects.filter(alquileres__in=Alquiler.objects.filter(filtros_alquiler)).distinct().count()
    ingresos_totales = sum(e.ingresos_generados for e in equipos)

    marcas = Equipo.objects.values_list('marca', flat=True).distinct().order_by('marca')

    labels = [f"{e.marca} {e.modelo}" for e in equipos]
    datos_alquileres = [e.total_alquileres for e in equipos]
    datos_ingresos = [float(e.ingresos_generados) for e in equipos]

    if 'export' in request.GET:
        if request.GET['export'] == 'excel':
            return exportar_a_excel(request, equipos, labels, datos_alquileres, datos_ingresos)

        elif request.GET['export'] == 'pdf':
            return exportar_a_pdf(request, equipos, labels, datos_alquileres, datos_ingresos,
                                  total_equipos, total_alquileres, total_clientes, ingresos_totales)


    return render(request, 'estadisticas.html', {
        'labels': json.dumps(labels),
        'datos': json.dumps(datos_alquileres),
        'ingresos_equipos': json.dumps(datos_ingresos),
        'equipos': equipos,
        'total_equipos': total_equipos,
        'total_alquileres': total_alquileres,
        'total_clientes': total_clientes,
        'ingresos_totales': ingresos_totales,
        'marcas': marcas,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'marca_seleccionada': marca,
        'agrupar_por': agrupar_por,
    })



@login_required
@permission_required('alquiler.export_reports', raise_exception=True)
def exportar_a_excel(request, equipos, labels, datos_alquileres, datos_ingresos):
    output = io.BytesIO()
    
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet('Estadísticas')
    
    # Formatos
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#3498db',
        'font_color': 'white',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1
    })
    
    data_format = workbook.add_format({
        'border': 1,
        'align': 'left'
    })
    
    number_format = workbook.add_format({
        'border': 1,
        'num_format': '#,##0'
    })
    
    currency_format = workbook.add_format({
        'border': 1,
        'num_format': '$#,##0.00'
    })
    
    # Escribir encabezados
    worksheet.write_row(0, 0, [
        'Equipo', 'Total Alquileres', 'Ingresos Generados', 
        'Precio Promedio', 'Disponibilidad', 'Clientes Frecuentes'
    ], header_format)
    
    # Escribir datos
    for row_num, equipo in enumerate(equipos, start=1):
        clientes_frecuentes = ', '.join(equipo.clientes_frecuentes) if equipo.clientes_frecuentes else 'N/A'
        
        worksheet.write(row_num, 0, f"{equipo.marca} {equipo.modelo}", data_format)
        worksheet.write_number(row_num, 1, equipo.total_alquileres, number_format)
        worksheet.write_number(row_num, 2, float(equipo.ingresos_generados), currency_format)
        worksheet.write_number(row_num, 3, float(equipo.precio_promedio), currency_format)
        worksheet.write(row_num, 4, f"{equipo.cantidad_disponible}/{equipo.cantidad_total}", data_format)
        worksheet.write(row_num, 5, clientes_frecuentes, data_format)
    
    # Añadir gráficos al Excel
    chart_sheet = workbook.add_worksheet('Gráficos')
    
    # Gráfico de barras para alquileres
    chart_alquileres = workbook.add_chart({'type': 'column'})
    chart_alquileres.add_series({
        'name': 'Total Alquileres',
        'categories': f'=Estadísticas!$A$2:$A${len(equipos)+1}',
        'values': f'=Estadísticas!$B$2:$B${len(equipos)+1}',
        'data_labels': {'value': True},
        'fill': {'color': '#3498db'}
    })
    chart_alquileres.set_title({'name': 'Equipos más alquilados'})
    chart_alquileres.set_x_axis({'name': 'Equipos'})
    chart_alquileres.set_y_axis({'name': 'Número de alquileres'})
    chart_sheet.insert_chart('B2', chart_alquileres, {'x_offset': 25, 'y_offset': 10})
    
    # Gráfico de barras para ingresos
    chart_ingresos = workbook.add_chart({'type': 'column'})
    chart_ingresos.add_series({
        'name': 'Ingresos Generados',
        'categories': f'=Estadísticas!$A$2:$A${len(equipos)+1}',
        'values': f'=Estadísticas!$C$2:$C${len(equipos)+1}',
        'data_labels': {'value': True, 'num_format': '$#,##0.00'},
        'fill': {'color': '#2ecc71'}
    })
    chart_ingresos.set_title({'name': 'Ingresos por equipo'})
    chart_ingresos.set_x_axis({'name': 'Equipos'})
    chart_ingresos.set_y_axis({'name': 'Ingresos ($)'})
    chart_sheet.insert_chart('B20', chart_ingresos, {'x_offset': 25, 'y_offset': 10})
    
    # Ajustar anchos de columna
    worksheet.set_column('A:A', 30)
    worksheet.set_column('B:B', 15)
    worksheet.set_column('C:C', 18)
    worksheet.set_column('D:D', 15)
    worksheet.set_column('E:E', 15)
    worksheet.set_column('F:F', 40)
    
    workbook.close()
    output.seek(0)
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=estadisticas_alquileres.xlsx'
    return response

@login_required
@permission_required('alquiler.export_reports', raise_exception=True)
def exportar_a_excel_mensual(labels, datos_alquileres, datos_ingresos):
    output = io.BytesIO()
    
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet('Estadísticas Mensuales')
    
    # Formatos
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#3498db',
        'font_color': 'white',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1
    })
    
    number_format = workbook.add_format({
        'border': 1,
        'num_format': '#,##0',
        'align': 'center'
    })
    
    currency_format = workbook.add_format({
        'border': 1,
        'num_format': '$#,##0.00',
        'align': 'center'
    })
    
    # Escribir encabezados
    worksheet.write_row(0, 0, [
        'Mes', 'Total Alquileres', 'Ingresos Generados'
    ], header_format)
    
    # Escribir datos
    for row_num, (mes, alquileres, ingresos) in enumerate(zip(labels, datos_alquileres, datos_ingresos), start=1):
        worksheet.write(row_num, 0, mes)
        worksheet.write_number(row_num, 1, alquileres, number_format)
        worksheet.write_number(row_num, 2, ingresos, currency_format)
    
    # Añadir gráficos al Excel
    chart_sheet = workbook.add_worksheet('Gráficos')
    
    # Gráfico de barras para alquileres
    chart_alquileres = workbook.add_chart({'type': 'column'})
    chart_alquileres.add_series({
        'name': 'Total Alquileres',
        'categories': f'=Estadísticas Mensuales!$A$2:$A${len(labels)+1}',
        'values': f'=Estadísticas Mensuales!$B$2:$B${len(labels)+1}',
        'data_labels': {'value': True},
        'fill': {'color': '#3498db'}
    })
    chart_alquileres.set_title({'name': 'Alquileres por mes'})
    chart_alquileres.set_x_axis({'name': 'Mes'})
    chart_alquileres.set_y_axis({'name': 'Número de alquileres'})
    chart_sheet.insert_chart('B2', chart_alquileres, {'x_offset': 25, 'y_offset': 10})
    
    # Gráfico de barras para ingresos
    chart_ingresos = workbook.add_chart({'type': 'column'})
    chart_ingresos.add_series({
        'name': 'Ingresos Generados',
        'categories': f'=Estadísticas Mensuales!$A$2:$A${len(labels)+1}',
        'values': f'=Estadísticas Mensuales!$C$2:$C${len(labels)+1}',
        'data_labels': {'value': True, 'num_format': '$#,##0.00'},
        'fill': {'color': '#2ecc71'}
    })
    chart_ingresos.set_title({'name': 'Ingresos por mes'})
    chart_ingresos.set_x_axis({'name': 'Mes'})
    chart_ingresos.set_y_axis({'name': 'Ingresos ($)'})
    chart_sheet.insert_chart('B20', chart_ingresos, {'x_offset': 25, 'y_offset': 10})
    
    # Ajustar anchos de columna
    worksheet.set_column('A:A', 20)
    worksheet.set_column('B:B', 18)
    worksheet.set_column('C:C', 20)
    
    workbook.close()
    output.seek(0)
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=estadisticas_mensuales.xlsx'
    return response

@login_required
def exportar_a_pdf(request, equipos, labels, datos_alquileres, datos_ingresos, 
                total_equipos, total_alquileres, total_clientes, ingresos_totales):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="estadisticas_alquileres.pdf"'
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Título
    elements.append(Paragraph("Estadísticas de Alquileres", styles['Title']))
    elements.append(Paragraph(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Paragraph(" ", styles['Normal']))  # Espacio
    
    # Resumen estadístico
    resumen_data = [
        ["Total Equipos", total_equipos],
        ["Total Alquileres", total_alquileres],
        ["Clientes Activos", total_clientes],
        ["Ingresos Totales", f"${ingresos_totales:,.2f}"]
    ]
    
    resumen_table = Table(resumen_data, colWidths=[200, 100])
    resumen_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6'))
    ]))
    elements.append(resumen_table)
    elements.append(Paragraph(" ", styles['Normal']))  # Espacio
    
    # Tabla de equipos
    if equipos:
        elements.append(Paragraph("Detalle por Equipo", styles['Heading2']))
        
        equipo_data = [["Equipo", "Alquileres", "Ingresos", "Precio Prom.", "Disponibilidad"]]
        
        for equipo in equipos:
            equipo_data.append([
                f"{equipo.marca} {equipo.modelo}",
                equipo.total_alquileres,
                f"${equipo.ingresos_generados:,.2f}",
                f"${equipo.precio_promedio:,.2f}",
                f"{equipo.cantidad_disponible}/{equipo.cantidad_total}"
            ])
        
        equipo_table = Table(equipo_data, colWidths=[180, 80, 90, 80, 100])
        equipo_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6'))
        ]))
        elements.append(equipo_table)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    
    return response

@login_required
@permission_required('alquiler.export_reports', raise_exception=True)
def exportar_a_pdf_mensual(labels, datos_alquileres, datos_ingresos, 
                          total_equipos, total_alquileres, total_clientes, ingresos_totales):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="estadisticas_mensuales.pdf"'
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Título
    elements.append(Paragraph("Estadísticas Mensuales de Alquileres", styles['Title']))
    elements.append(Paragraph(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Paragraph(" ", styles['Normal']))  # Espacio
    
    # Resumen estadístico
    resumen_data = [
        ["Total Equipos", total_equipos],
        ["Total Alquileres", total_alquileres],
        ["Clientes Activos", total_clientes],
        ["Ingresos Totales", f"${ingresos_totales:,.2f}"]
    ]
    
    resumen_table = Table(resumen_data, colWidths=[200, 100])
    resumen_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6'))
    ]))
    elements.append(resumen_table)
    elements.append(Paragraph(" ", styles['Normal']))  # Espacio
    
    # Tabla mensual
    elements.append(Paragraph("Detalle Mensual", styles['Heading2']))
    
    mensual_data = [["Mes", "Alquileres", "Ingresos"]]
    
    for mes, alquileres, ingresos in zip(labels, datos_alquileres, datos_ingresos):
        mensual_data.append([
            mes,
            alquileres,
            f"${ingresos:,.2f}"
        ])
    
    mensual_table = Table(mensual_data, colWidths=[120, 100, 120])
    mensual_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6'))
    ]))
    elements.append(mensual_table)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    
    return response