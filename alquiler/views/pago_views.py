from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from datetime import timedelta
from django.utils import timezone
from decimal import Decimal
import csv
import json
from ..models import Pago, Alquiler, Cliente
from ..forms import FiltroPagosForm, PagoForm, PagoParcialForm
from django.contrib import messages
from ..serializers import PagoSerializer, PagoDetalleSerializer
from ..utils import enviar_notificacion_pago
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.template.loader import get_template
from xhtml2pdf import pisa
from io import BytesIO
from django.db.models import Count, Sum, Max
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.db.models import  Avg, Q
from django.utils import timezone
from datetime import timedelta, datetime
import csv
import json
import decimal
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from email.mime.image import MIMEImage
import traceback
from django.core.paginator import Paginator
from calendar import monthrange
from django.db.models.functions import TruncMonth, TruncDay, TruncWeek
import logging
logger = logging.getLogger(__name__)

@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def reportes_pagos(request):
    """Vista principal de reportes de pagos con gráficas y análisis avanzado"""

    # Configurar fechas por defecto (últimos 30 días)
    fecha_fin_default = timezone.now().date()
    fecha_inicio_default = fecha_fin_default - timedelta(days=30)

    # Procesar filtros del formulario
    fecha_inicio_str = request.GET.get('fecha_inicio', '')
    fecha_fin_str = request.GET.get('fecha_fin', '')
    estado = request.GET.get('estado', '')
    metodo_pago = request.GET.get('metodo_pago', '')
    periodo = request.GET.get('periodo', 'mensual')  # diario, semanal, mensual

    # Convertir fechas de string a date objects
    if fecha_inicio_str:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
    else:
        fecha_inicio = fecha_inicio_default

    if fecha_fin_str:
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    else:
        fecha_fin = fecha_fin_default

    # Obtener todos los pagos con filtros de fecha
    pagos = Pago.objects.select_related('alquiler', 'alquiler__cliente').filter(
        fecha_pago__gte=fecha_inicio,
        fecha_pago__lte=fecha_fin
    )

    # Aplicar otros filtros
    if estado:
        pagos = pagos.filter(estado_pago=estado)
    if metodo_pago:
        pagos = pagos.filter(metodo_pago=metodo_pago)


    # Exportar a CSV si se solicita (esta función ya la tienes)
    if request.GET.get('export') == 'csv':
        return exportar_csv_pagos(pagos, fecha_inicio, fecha_fin)

    # Calcular métricas principales
    metricas = calcular_metricas_pagos(pagos)

    # Obtener datos para gráficas
    datos_graficas = obtener_datos_graficas(pagos, periodo, fecha_inicio, fecha_fin)

    # Análisis de tendencias
    tendencias = analizar_tendencias(pagos, fecha_inicio, fecha_fin)

    # Top clientes
    top_clientes = obtener_top_clientes(pagos)

    # Obtener opciones para filtros (asume que Pago.ESTADO_PAGO y Pago.METODOS están definidos en tu modelo)
    estados = Pago.ESTADO_PAGO
    metodos_pago = Pago.METODOS

    context = {
        'pagos': pagos.order_by('-fecha_pago')[:50],  # Últimos 50 para vista previa
        'metricas': metricas,
        'datos_graficas': json.dumps(datos_graficas, default=str), # default=str es crucial para fechas
        'tendencias': tendencias,
        'top_clientes': top_clientes,
        'estados': estados,
        'metodos_pago': metodos_pago,
        'fecha_inicio': fecha_inicio.strftime('%Y-%m-%d'),
        'fecha_fin': fecha_fin.strftime('%Y-%m-%d'),
        'periodo_actual': periodo,
        'total_registros': pagos.count(),
    }

    return render(request, 'reportes_pagos.html', context)

def calcular_metricas_pagos(pagos):
    """Calcula métricas principales de los pagos"""
    total_pagado = pagos.filter(estado_pago='pagado').aggregate(total=Sum('monto'))['total'] or 0
    total_pendiente = pagos.filter(estado_pago='pendiente').aggregate(total=Sum('monto'))['total'] or 0
    total_parcial = pagos.filter(estado_pago='parcial').aggregate(total=Sum('monto'))['total'] or 0

    total_pagos = pagos.count()
    pagos_completados = pagos.filter(estado_pago='pagado').count()
    pagos_pendientes = pagos.filter(estado_pago='pendiente').count()
    pagos_vencidos = pagos.filter(
        estado_pago__in=['pendiente', 'parcial'],
        fecha_vencimiento__lt=timezone.now().date()
    ).count()

    # Evitar ZeroDivisionError
    promedio_pago = total_pagado / pagos_completados if pagos_completados > 0 else 0
    tasa_cumplimiento = (pagos_completados / total_pagos * 100) if total_pagos > 0 else 0

    return {
        'total_pagado': total_pagado,
        'total_pendiente': total_pendiente,
        'total_parcial': total_parcial,
        'total_pagos': total_pagos,
        'pagos_completados': pagos_completados,
        'pagos_pendientes': pagos_pendientes,
        'pagos_vencidos': pagos_vencidos,
        'promedio_pago': round(promedio_pago, 2),
        'tasa_cumplimiento': round(tasa_cumplimiento, 2),
    }


def obtener_datos_graficas(pagos, periodo, fecha_inicio, fecha_fin):
    """Obtiene datos para las gráficas según el período seleccionado"""

    # Configurar el truncado según el período
    if periodo == 'diario':
        trunc_func = TruncDay
        format_key = lambda x: x.strftime('%Y-%m-%d')
    elif periodo == 'semanal':
        trunc_func = TruncWeek
        # Para semanas, aseguramos que la fecha_pago caiga en el rango correcto
        format_key = lambda x: f"Semana {x.strftime('%U')}/{x.year}"
    else:  # mensual
        trunc_func = TruncMonth
        format_key = lambda x: x.strftime('%Y-%m')

    # Evolución de pagos por período
    # Aseguramos que los pagos estén dentro del rango de fechas seleccionado antes de truncar
    evolucion_pagos_queryset = pagos.annotate(
        periodo=trunc_func('fecha_pago')
    ).values('periodo').annotate(
        total_monto=Sum('monto'),
        cantidad_pagos=Count('id'),
        pagos_completados=Count('id', filter=Q(estado_pago='pagado')),
        pagos_pendientes=Count('id', filter=Q(estado_pago='pendiente'))
    ).order_by('periodo')

    evolucion_pagos = list(evolucion_pagos_queryset)

    # Si no hay datos, inicializar con arrays vacíos
    labels = [format_key(item['periodo']) for item in evolucion_pagos if item['periodo']]
    montos = [float(item['total_monto']) for item in evolucion_pagos]
    cantidades = [item['cantidad_pagos'] for item in evolucion_pagos]
    completados = [item['pagos_completados'] for item in evolucion_pagos]
    pendientes = [item['pagos_pendientes'] for item in evolucion_pagos]

    # Distribución por estado
    distribucion_estados = list(pagos.values('estado_pago').annotate(
        total=Sum('monto'),
        cantidad=Count('id')
    ).order_by('-total'))

    # Distribución por método de pago
    distribucion_metodos = list(pagos.values('metodo_pago').annotate(
        total=Sum('monto'),
        cantidad=Count('id')
    ).order_by('-total'))

    return {
        'evolucion': {
            'labels': labels,
            'montos': [float(m) for m in montos],  # Asegurar conversión a float
            'cantidades': cantidades,
            'completados': completados,
            'pendientes': pendientes
        },
        'estados': {
            'labels': [dict(Pago.ESTADO_PAGO).get(item['estado_pago'], item['estado_pago']) for item in distribucion_estados],
            'data': [float(item['total']) for item in distribucion_estados],  # Conversión a float
            'cantidades': [item['cantidad'] for item in distribucion_estados]
        },
        'metodos': {
            'labels': [dict(Pago.METODOS).get(item['metodo_pago'], item['metodo_pago']) for item in distribucion_metodos if item['metodo_pago']],  # Filtrar valores vacíos
            'data': [float(item['total']) for item in distribucion_metodos if item['metodo_pago']],  # Filtrar y convertir
            'cantidades': [item['cantidad'] for item in distribucion_metodos if item['metodo_pago']]
        }
    }

def analizar_tendencias(pagos, fecha_inicio, fecha_fin):
    """Analiza tendencias de pagos comparando con períodos anteriores"""

    # Calcular período anterior
    dias_periodo = (fecha_fin - fecha_inicio).days + 1 # +1 para incluir ambos días
    fecha_inicio_anterior = fecha_inicio - timedelta(days=dias_periodo)
    fecha_fin_anterior = fecha_fin - timedelta(days=dias_periodo)

    # Pagos período actual
    pagos_actuales = pagos.filter(
        fecha_pago__gte=fecha_inicio,
        fecha_pago__lte=fecha_fin
    )

    # Pagos período anterior (solo del modelo Pago, sin aplicar filtros del request)
    pagos_anteriores = Pago.objects.filter(
        fecha_pago__gte=fecha_inicio_anterior,
        fecha_pago__lte=fecha_fin_anterior
    )

    # Métricas actuales
    total_actual = pagos_actuales.aggregate(total=Sum('monto'))['total'] or 0
    cantidad_actual = pagos_actuales.count()

    # Métricas anteriores
    total_anterior = pagos_anteriores.aggregate(total=Sum('monto'))['total'] or 0
    cantidad_anterior = pagos_anteriores.count()

    # Calcular variaciones, evitando ZeroDivisionError
    variacion_monto = ((total_actual - total_anterior) / total_anterior * 100) if total_anterior > 0 else (100 if total_actual > 0 else 0)
    variacion_cantidad = ((cantidad_actual - cantidad_anterior) / cantidad_anterior * 100) if cantidad_anterior > 0 else (100 if cantidad_actual > 0 else 0)

    return {
        'total_actual': total_actual,
        'total_anterior': total_anterior,
        'cantidad_actual': cantidad_actual,
        'cantidad_anterior': cantidad_anterior,
        'variacion_monto': round(variacion_monto, 2),
        'variacion_cantidad': round(variacion_cantidad, 2),
    }


def obtener_top_clientes(pagos):
    """Obtiene los clientes con más pagos/montos"""
    # Se agrega .distinct() si un cliente puede tener múltiples alquileres y quieres sumarlos una vez
    # Pero si quieres por cliente individual en cada pago, esto está bien
    top_clientes_list = list(pagos.values(
        'alquiler__cliente__nombre',
        'alquiler__cliente__email'
    ).annotate(
        total_pagado=Sum('monto'),
        cantidad_pagos=Count('id'),
        ultimo_pago=Max('fecha_pago')
    ).order_by('-total_pagado')[:10])

    return top_clientes_list


def exportar_csv_pagos(pagos, fecha_inicio, fecha_fin):
    """Exporta los pagos filtrados a CSV"""
    response = HttpResponse(content_type='text/csv')
    filename = f'reporte_pagos_{fecha_inicio}_{fecha_fin}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Número Factura', 'Fecha', 'Cliente', 'Email', 'Alquiler', 
        'Monto', 'Método de Pago', 'Estado', 'Fecha Vencimiento', 'Referencia'
    ])
    
    for pago in pagos:
        writer.writerow([
            pago.id,
            pago.alquiler.numero_factura or '',
            pago.fecha_pago.strftime('%d/%m/%Y'),
            pago.alquiler.cliente.nombre,
            pago.alquiler.cliente.email,
            pago.alquiler.id,
            pago.monto,
            pago.get_metodo_pago_display(),
            pago.get_estado_pago_display(),
            pago.fecha_vencimiento.strftime('%d/%m/%Y') if pago.fecha_vencimiento else '',
            pago.referencia_transaccion or ''
        ])
    
    return response


@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def listar_pagos(request):
    pagos = Pago.objects.select_related('alquiler', 'alquiler__cliente')
    

    numero_factura = request.GET.get('numero_factura', '').strip()
    cliente = request.GET.get('cliente', '').strip()
    estado = request.GET.get('estado')
    metodo_pago = request.GET.get('metodo_pago')
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    monto_min = request.GET.get('monto_min')
    monto_max = request.GET.get('monto_max')
    

    if numero_factura:

        pagos = pagos.filter(alquiler__numero_factura__icontains=numero_factura)
    
    if cliente:
        pagos = pagos.filter(
            Q(alquiler__cliente__nombre__icontains=cliente) |
            Q(alquiler__cliente__email__icontains=cliente)
        )
    
    if estado:
        pagos = pagos.filter(estado_pago=estado)
    
    if metodo_pago:
        pagos = pagos.filter(metodo_pago=metodo_pago)
    
    if fecha_inicio:
        pagos = pagos.filter(fecha_pago__gte=fecha_inicio)
    
    if fecha_fin:
        pagos = pagos.filter(fecha_pago__lte=fecha_fin)
    
    if monto_min:
        try:
            pagos = pagos.filter(monto__gte=float(monto_min))
        except ValueError:
            pass 
    if monto_max:
        try:
            pagos = pagos.filter(monto__lte=float(monto_max))
        except ValueError:
            pass 
    pagos = pagos.order_by('-fecha_pago')
    
    
    total_pagado = pagos.filter(estado_pago='pagado').aggregate(
        Sum('monto'))['monto__sum'] or 0
    total_pendiente = pagos.filter(estado_pago='pendiente').aggregate(
        Sum('monto'))['monto__sum'] or 0
    total_parcial = pagos.filter(estado_pago='parcial').aggregate(
        Sum('monto'))['monto__sum'] or 0
    
    pagos_pendientes = pagos.filter(estado_pago='pendiente').count()
    hoy = timezone.now().date() 
    pagos_vencidos = pagos.filter(
        estado_pago__in=['pendiente', 'parcial'],
        fecha_vencimiento__lt=hoy 
    ).count()
    pagos_parciales = pagos.filter(estado_pago='parcial').count()
    
    
    paginator = Paginator(pagos, 10)  
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    

    context = {
        'pagos': page_obj,
        'total_pagado': total_pagado,
        'total_pendiente': total_pendiente,
        'total_parcial': total_parcial,
        'pagos_pendientes': pagos_pendientes,
        'pagos_vencidos': pagos_vencidos,
        'pagos_parciales': pagos_parciales,
        'estados_pago': Pago.ESTADO_PAGO, 
        'metodos_pago': Pago.METODOS,   
        'total_registros': pagos.count(),
        'filtros_activos': any([
            numero_factura, cliente, estado, metodo_pago, 
            fecha_inicio, fecha_fin, monto_min, monto_max
        ]),
        'hoy': hoy, 
    }
    
    return render(request, 'lista_pagos.html', context)


@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def api_datos_graficas(request):
    """API para obtener datos de gráficas de forma dinámica"""
    tipo_grafica = request.GET.get('tipo', 'evolucion')
    periodo = request.GET.get('periodo', 'mensual')
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    
    # Aplicar filtros base
    pagos = Pago.objects.all()
    
    if fecha_inicio:
        pagos = pagos.filter(fecha_pago__gte=fecha_inicio)
    if fecha_fin:
        pagos = pagos.filter(fecha_pago__lte=fecha_fin)
    
    if tipo_grafica == 'evolucion':
        datos = obtener_datos_graficas(pagos, periodo, 
                                     datetime.strptime(fecha_inicio, '%Y-%m-%d').date(),
                                     datetime.strptime(fecha_fin, '%Y-%m-%d').date())
        return JsonResponse(datos['evolucion'])
    
    elif tipo_grafica == 'estados':
        datos = obtener_datos_graficas(pagos, periodo, 
                                     datetime.strptime(fecha_inicio, '%Y-%m-%d').date(),
                                     datetime.strptime(fecha_fin, '%Y-%m-%d').date())
        return JsonResponse(datos['estados'])
    
    elif tipo_grafica == 'metodos':
        datos = obtener_datos_graficas(pagos, periodo, 
                                     datetime.strptime(fecha_inicio, '%Y-%m-%d').date(),
                                     datetime.strptime(fecha_fin, '%Y-%m-%d').date())
        return JsonResponse(datos['metodos'])
    
    return JsonResponse({'error': 'Tipo de gráfica no válido'}, status=400)


@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def pagos_vencidos(request):
    hoy = timezone.now().date()
    print(f"===> Entrando a pagos_vencidos. Hoy: {hoy}")

    try:
        pagos = Pago.objects.filter(
            estado_pago__in=['pendiente', 'parcial'],
            fecha_vencimiento__lt=hoy
        ).order_by('fecha_vencimiento')

        print(f"Total pagos encontrados: {pagos.count()}")
        for p in pagos:
            print(f"Pago ID={p.id}, UUID={p.uuid_id}, estado={p.estado_pago}, "
                  f"fecha_vencimiento={p.fecha_vencimiento}, monto={p.monto}, "
                  f"alquiler={p.alquiler_id if p.alquiler else 'SIN ALQUILER'}")

    except Exception as e:
        print(">>> ERROR al obtener pagos vencidos:", str(e))
        pagos = Pago.objects.none()

    try:
        total_vencido = pagos.aggregate(total=Sum('monto'))['total'] or 0
        print(f"Total vencido: {total_vencido}")
    except Exception as e:
        print(">>> ERROR al calcular total vencido:", str(e))
        total_vencido = 0

    return render(request, 'pagos_vencidos.html', {
        'pagos': pagos,
        'total_vencido': total_vencido,
        'titulo': 'Pagos Vencidos'
    })



@login_required
@permission_required('alquiler.change_pago', raise_exception=True)
def cambiar_estado_pago(request, pago_uuid, nuevo_estado):
    pago = get_object_or_404(Pago, uuid_id=pago_uuid)
    estado_anterior = pago.estado_pago

    if nuevo_estado not in dict(Pago.ESTADO_PAGO):
        messages.error(request, 'Estado inválido')
        return redirect('alquiler:detalle_pago', pago_uuid=pago.uuid_id)

    try:
        # Actualizar estado del pago
        pago.estado_pago = nuevo_estado
        pago.aprobado_por = request.user
        pago.save()

        # Verificar estado del alquiler relacionado
        verificar_estado_pago_alquiler(pago.alquiler)

        # Notificación solo para pagos aprobados
        if nuevo_estado == 'pagado' and estado_anterior != 'pagado':
            enviar_confirmacion_pago(pago)
            messages.success(request, 'Pago aprobado y notificación enviada al cliente')
        else:
            messages.success(request, f'Estado del pago actualizado a {pago.get_estado_pago_display()}')

    except Exception as e:
        messages.error(request, f"Ocurrió un error al actualizar el estado del pago: {str(e)}")

    return redirect('alquiler:detalle_pago', pago_uuid=pago.uuid_id)



def enviar_confirmacion_pago(pago):
    try:
        cliente = pago.alquiler.cliente
        contexto = {
            'nombre_cliente': cliente.nombre,
            'numero_factura': pago.alquiler.numero_factura,
            'fecha_pago': pago.fecha_pago.strftime("%d/%m/%Y"),
            'monto_pagado': pago.monto,
            'fecha_vencimiento': pago.alquiler.fecha_fin.strftime("%d/%m/%Y"),
            'equipos': [f"{d.equipo.marca} {d.equipo.modelo}" for d in pago.alquiler.detalles.all()]
        }

        # Renderizar contenido
        html_content = render_to_string('confirmacion_pago.html', contexto)
        text_content = strip_tags(html_content)

        # Configurar y enviar email
        email = EmailMultiAlternatives(
            subject=f'Confirmación de pago #{pago.alquiler.numero_factura}',
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[cliente.email]
        )
        email.attach_alternative(html_content, "text/html")
        email.send(fail_silently=False)
        
        # Registrar el envío (opcional)
        pago.notificacion_enviada = True
        pago.save()

    except Exception as e:
        logger.error(f"Error enviando confirmación de pago {pago.id}: {str(e)}")



@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def pagos_proximos_vencer(request):
    hoy = timezone.now().date()
    fecha_limite = hoy + timedelta(days=3)  # Próximos 3 días
    
    pagos = Pago.objects.filter(
        estado_pago__in=['pendiente', 'parcial'],
        fecha_vencimiento__range=[hoy, fecha_limite]
    ).order_by('fecha_vencimiento')
    
    return render(request, 'pagos_proximos.html', {
        'pagos': pagos,
        'titulo': 'Pagos Próximos a Vencer'
    })


@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def detalle_pago(request, pago_uuid):
    pago = get_object_or_404(Pago, uuid_id=pago_uuid)

    # Determinar quién aprobó
    if hasattr(pago.aprobado_por, 'get_full_name') and pago.aprobado_por.get_full_name():
        nombre_aprobador = pago.aprobado_por.get_full_name()
    elif hasattr(pago.aprobado_por, 'email'):
        nombre_aprobador = pago.aprobado_por.email
    else:
        nombre_aprobador = str(pago.aprobado_por) if pago.aprobado_por else "Sistema"

    # ✅ Protegemos alquiler y cliente
    alquiler = pago.alquiler if pago.alquiler else None
    cliente = alquiler.cliente if (alquiler and getattr(alquiler, "cliente", None)) else None

    context = {
        'pago': pago,
        'alquiler': alquiler,
        'cliente': cliente,
        'nombre_aprobador': nombre_aprobador,
    }
    return render(request, 'detalle_pago.html', context)



@login_required
@permission_required('alquiler.add_pago', raise_exception=True)
def registrar_pago(request):
    if request.method == 'POST':
        form = PagoForm(request.POST, request.FILES)
        if form.is_valid():
            pago = form.save(commit=False)
            pago.aprobado_por = request.user
            pago.save()
            
            # Actualizar estado del alquiler solo si existe y corresponde
            if pago.estado_pago == 'pagado' and pago.alquiler:
                pago.alquiler.estado_alquiler = 'finalizado'
                pago.alquiler.save()
            
            return redirect('alquiler:detalle_pago', pago_uuid=pago.uuid_id)
    else:
        form = PagoForm()
    
    return render(request, 'registrar_pago.html', {'form': form})


@login_required
@permission_required('alquiler.change_pago', raise_exception=True)
def editar_pago(request, pago_uuid):
    print(f"===> Ingresando a editar_pago con ID: {pago_uuid}")
    pago = get_object_or_404(Pago, uuid_id=pago_uuid)
    print(f"Pago obtenido: {pago}")

    if not pago.alquiler:
        messages.error(request, "Este pago no está vinculado a ningún alquiler.")
        return redirect('alquiler:listar_pagos')

    if request.method == 'POST':
        print("Método: POST")
        form = PagoForm(request.POST, request.FILES, instance=pago)
        if form.is_valid():
            print("Formulario válido")
            
            pago = form.save(commit=False)


            if pago.alquiler is None: 
                messages.error(request, "El pago debe estar vinculado a un alquiler válido. Por favor, seleccione uno.")

                context = {
                    'form': form,
                    'pago': pago,
                    'titulo': f'Editar Pago #{pago.uuid_id}'
                }
                return render(request, 'editar_pago.html', context)

            pago.aprobado_por = request.user
            print(f"Pago aprobado por: {pago.aprobado_por}")

            total_pagado = pago.alquiler.pagos.filter(estado_pago__in=['pagado', 'parcial']).exclude(uuid_id=pago.uuid_id).aggregate(
                total=Sum('monto')
            )['total'] or decimal.Decimal('0.00')

            print(f"Total pagado antes del nuevo monto: {total_pagado}")

            total_pagado += pago.monto 
            print(f"Total pagado incluyendo el nuevo monto: {total_pagado}")
            print(f"Precio total del alquiler: {pago.alquiler.precio_total}")

            if total_pagado >= pago.alquiler.precio_total:
                pago.estado_pago = 'pagado'
                pago.alquiler.estado_alquiler = 'finalizado'
                pago.alquiler.save()
                print("Pago completo. Alquiler finalizado.")
            else:
                pago.estado_pago = 'parcial'

                print("Pago parcial.")

            pago.save()
            print(f"Pago actualizado y guardado: {pago}")
            messages.success(request, 'Pago actualizado correctamente')
            return redirect('alquiler:detalle_pago', pago_uuid=pago.uuid_id)
        else:
            print("Formulario inválido")
            print("Errores del formulario:", form.errors)
    else: 
        print("Método: GET")
        form = PagoForm(instance=pago)

    context = {
        'form': form,
        'pago': pago,
        'titulo': f'Editar Pago #{pago.uuid_id}'
    }
    return render(request, 'editar_pago.html', context)



@login_required
@permission_required('alquiler.delete_pago', raise_exception=True)
def eliminar_pago(request, pago_uuid):
    print(f"===> Entrando a eliminar_pago con ID: {pago_uuid}")
    pago = get_object_or_404(Pago, id=pago_uuid)
    print(f"Pago obtenido: {pago}")

    if request.method == 'POST':
        print("Método: POST - eliminando pago...")
        pago.delete()
        print(f"Pago #{pago_uuid} eliminado.")
        messages.success(request, f'Pago #{pago_uuid} eliminado correctamente.')
        return redirect('alquiler:lista_pagos')
    
    print("Método: GET - mostrando plantilla de confirmación")
    context = {
        'pago': pago,
        'titulo': f'Confirmar eliminación del Pago #{pago.uuid}'
    }
    return render(request, 'eliminar_pago.html', context)


@login_required
@permission_required('alquiler.view_factura', raise_exception=True)
def generar_factura_pdf(request, pago_uuid):
    pago = get_object_or_404(Pago, uuid_id=pago_uuid)

    
    # Renderizar template
    template = get_template('factura_pdf.html')
    context = {
        'pago': pago,
        'alquiler': pago.alquiler,
        'cliente': pago.alquiler.cliente,
        'fecha': timezone.now().date(),
    }
    html = template.render(context)
    
    # Crear PDF
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    
    if not pdf.err:
        pago.factura_generada = True
        pago.save()
        
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="factura_{pago.uuid_id}.pdf"'
        return response
    
    return HttpResponse("Error al generar el PDF", status=400)

@login_required
def verificar_morosidad_cliente(cliente_uuid):
    cliente = get_object_or_404(Cliente, id=cliente_uuid)
    pagos_vencidos = Pago.objects.filter(
        alquiler__cliente=cliente,
        estado_pago__in=['pendiente', 'parcial'],
        fecha_vencimiento__lt=timezone.now().date()
    ).exists()
    
    if pagos_vencidos:
        cliente.estado_verificacion = 'rechazado'
        cliente.moroso = True
        cliente.fecha_marcado_moroso = timezone.now().date()
        cliente.save()
        return True
    return False


@login_required
@permission_required('alquiler.view_pago', raise_exception=True)
def pagos_parciales(request):
    # Obtener solo pagos parciales
    pagos = Pago.objects.filter(estado_pago='parcial').order_by('-fecha_pago')
    
    # Calcular total parcial
    total_parcial = pagos.aggregate(total=Sum('monto'))['total'] or 0
    
    # Calcular saldo pendiente promedio (solo de pagos con alquiler válido)
    saldos = [
        float(pago.alquiler.saldo_pendiente)
        for pago in pagos
        if pago.alquiler and pago.alquiler.saldo_pendiente is not None
    ]
    
    saldo_promedio = sum(saldos) / len(saldos) if saldos else 0
    
    context = {
        'pagos': pagos,
        'total_parcial': total_parcial,
        'saldo_promedio': round(saldo_promedio, 2),
    }
    
    return render(request, 'pagos_parciales.html', context)




@login_required
@permission_required('alquiler.add_pago', raise_exception=True)
def registrar_pago_parcial(request):
    if request.method == 'POST':
        form = PagoParcialForm(request.POST, request.FILES)
        if form.is_valid():
            pago = form.save(commit=False)
            pago.estado_pago = 'parcial'  # Forzar estado parcial
            pago.save()

            messages.success(request, f'Pago parcial #{pago.id} registrado correctamente.')
            return redirect('alquiler:detalle_pago', pago_uuid=pago.uuid_id)
    else:
        alquiler_uuid = request.GET.get('alquiler_id')
        initial = {}
        alquiler = None

        if alquiler_uuid:
            try:
                alquiler = Alquiler.objects.get(uuid_id=alquiler_uuid)
                initial = {
                    'alquiler': alquiler,
                    'monto': alquiler.saldo_pendiente * Decimal('0.5'),
                }
            except Alquiler.DoesNotExist:
                messages.error(request, 'El alquiler especificado no existe.')

        form = PagoParcialForm(initial=initial)

    context = {
        'form': form,
        'alquiler': alquiler  # Ya tienes la instancia
    }

    return render(request, 'registrar_pago_parcial.html', context)


def verificar_estado_pago_alquiler(alquiler):
    if not alquiler:
        return

    total_pagado = alquiler.pagos.filter(
        estado_pago__in=['pagado', 'parcial']
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    if total_pagado > 0:
        alquiler.estado_alquiler = 'activo'
        alquiler.save(update_fields=['estado_alquiler'])





class RegistrarPagoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Registra un nuevo pago para un alquiler.
        Puede ser un pago completo o parcial.
        """
        serializer = PagoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        alquiler = get_object_or_404(Alquiler, id=serializer.validated_data['alquiler_id'])
        monto = Decimal(serializer.validated_data['monto'])
        
        # Validar que el monto no exceda el saldo pendiente
        saldo_pendiente = alquiler.saldo_pendiente
        if monto > saldo_pendiente + Decimal('0.01'):  # Tolerancia para decimales
            return Response(
                {"error": f"El monto excede el saldo pendiente (${saldo_pendiente})"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Determinar estado del pago
        estado_pago = 'pagado' if monto >= saldo_pendiente else 'parcial'

        try:
            pago = Pago.objects.create(
                alquiler=alquiler,
                monto=monto,
                metodo_pago=serializer.validated_data['metodo_pago'],
                estado_pago=estado_pago,
                referencia_transaccion=serializer.validated_data.get('referencia_transaccion', ''),
                aprobado_por=request.user,
                fecha_vencimiento=timezone.now().date() + timedelta(days=2)  # 15 días para pagar
            )

            # Actualizar estado del alquiler si está completamente pagado
            if estado_pago == 'pagado':
                alquiler.estado_alquiler = 'finalizado'
                alquiler.save()
                # Marcar todos los pagos parciales como completados
                alquiler.pagos.filter(estado_pago='parcial').update(estado_pago='pagado')

            # Enviar notificación
            enviar_notificacion_pago(pago, request.user)

            return Response(PagoDetalleSerializer(pago).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": f"Error al registrar el pago: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PagosAlquilerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, alquiler_id):
        """
        Obtiene todos los pagos de un alquiler específico
        """
        alquiler = get_object_or_404(Alquiler, id=alquiler_id)
        pagos = alquiler.pagos.all().order_by('-fecha_pago')
        serializer = PagoDetalleSerializer(pagos, many=True)
        
        data = {
            'pagos': serializer.data,
            'total_pagado': alquiler.total_pagado,
            'saldo_pendiente': alquiler.saldo_pendiente,
            'porcentaje_pagado': alquiler.porcentaje_pagado
        }
        
        return Response(data)


class PagoDetalleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pago_id):
        """
        Obtiene los detalles de un pago específico
        """
        pago = get_object_or_404(Pago, id=pago_id)
        serializer = PagoDetalleSerializer(pago)
        return Response(serializer.data)

    def put(self, request, pago_id):
        """
        Actualiza un pago (por ejemplo, para aprobación/rechazo)
        """
        pago = get_object_or_404(Pago, id=pago_id)
        
        # Solo permitir actualizar ciertos campos
        data = request.data.copy()
        allowed_fields = ['estado_pago', 'referencia_transaccion', 'comprobante_pago', 'notas']
        for field in list(data.keys()):
            if field not in allowed_fields:
                data.pop(field)
        
        serializer = PagoDetalleSerializer(pago, data=data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        serializer.save(aprobado_por=request.user)
        
        # Si se rechaza el pago, verificar si el cliente debe ser marcado como moroso
        if serializer.validated_data.get('estado_pago') == 'rechazado':
            verificar_morosidad_cliente(pago.alquiler.cliente.id)
        
        return Response(serializer.data)


class PagosPendientesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Lista todos los pagos pendientes con filtros opcionales
        """
        queryset = Pago.objects.filter(estado_pago__in=['pendiente', 'parcial'])
        
        # Filtros
        cliente_id = request.query_params.get('cliente_id')
        alquiler_id = request.query_params.get('alquiler_id')
        fecha_vencimiento = request.query_params.get('fecha_vencimiento')
        
        if cliente_id:
            queryset = queryset.filter(alquiler__cliente__id=cliente_id)
        if alquiler_id:
            queryset = queryset.filter(alquiler__id=alquiler_id)
        if fecha_vencimiento:
            queryset = queryset.filter(fecha_vencimiento=fecha_vencimiento)
        
        serializer = PagoDetalleSerializer(queryset.order_by('fecha_vencimiento'), many=True)
        return Response(serializer.data)


class GenerarFacturaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pago_id):
        """
        Genera una factura para un pago específico
        """
        pago = get_object_or_404(Pago, id=pago_id)
        
        # Aquí iría la lógica real para generar el PDF de la factura
        # Por ahora simulamos la generación
        factura_data = {
            "numero_factura": f"FACT-{pago.id:05d}",
            "fecha": timezone.now().date().strftime("%Y-%m-%d"),
            "cliente": pago.alquiler.cliente.nombre,
            "monto": pago.monto,
            "metodo_pago": pago.get_metodo_pago_display(),
            "referencia": pago.referencia_transaccion or "N/A"
        }
        
        pago.factura_generada = True
        pago.save()
        
        return Response({
            "mensaje": "Factura generada exitosamente",
            "factura": factura_data,
            "descarga_url": f"/api/pagos/{pago.id}/factura/pdf/"  # URL ficticia para descarga
        })


class PasarelaPagoView(APIView):
    def post(self, request):
        """
        Inicia un pago a través de una pasarela de pago externa
        """
        alquiler_id = request.data.get('alquiler_id')
        monto = request.data.get('monto')
        
        if not alquiler_id or not monto:
            return Response(
                {"error": "Se requieren alquiler_id y monto"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        alquiler = get_object_or_404(Alquiler, id=alquiler_id)
        
        # Validar que el monto no exceda el saldo pendiente
        if Decimal(monto) > alquiler.saldo_pendiente:
            return Response(
                {"error": f"El monto excede el saldo pendiente (${alquiler.saldo_pendiente})"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Simulación de integración con pasarela de pago
        # En producción, aquí se haría la conexión real con PayPal, Stripe, etc.
        payment_data = {
            "payment_id": f"pay_{timezone.now().timestamp()}",
            "status": "created",
            "approval_url": f"https://pasarela-pago.example.com/pay?amount={monto}&alquiler={alquiler_id}",
            "monto": monto,
            "moneda": "COP",
            "fecha_expiracion": (timezone.now() + timedelta(minutes=30)).isoformat()
        }
        
        # Guardar temporalmente la información del pago pendiente
        request.session['pending_payment'] = json.dumps({
            "alquiler_id": alquiler_id,
            "monto": monto,
            "payment_data": payment_data
        })
        
        return Response(payment_data)


class ProcesarPagoPasarelaView(APIView):
    def get(self, request):
        """
        Callback para procesar la respuesta de la pasarela de pago
        """
        payment_status = request.query_params.get('status')
        payment_id = request.query_params.get('payment_id')
        
        if not payment_status or not payment_id:
            return Response(
                {"error": "Faltan parámetros en la URL"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Recuperar datos del pago pendiente
        pending_payment = request.session.get('pending_payment')
        if not pending_payment:
            return Response(
                {"error": "No se encontró información del pago pendiente"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        payment_data = json.loads(pending_payment)
        alquiler = get_object_or_404(Alquiler, id=payment_data['alquiler_id'])
        
        if payment_status == 'approved':
            # Registrar el pago exitoso
            pago = Pago.objects.create(
                alquiler=alquiler,
                monto=payment_data['monto'],
                metodo_pago='tarjeta',  # o el método correspondiente
                estado_pago='pagado',
                referencia_transaccion=payment_id,
                fecha_vencimiento=timezone.now().date()
            )
            
            # Actualizar estado del alquiler si corresponde
            if alquiler.saldo_pendiente <= 0:
                alquiler.estado_alquiler = 'finalizado'
                alquiler.save()
            
            # Limpiar sesión
            del request.session['pending_payment']
            
            return Response({
                "status": "success",
                "message": "Pago registrado exitosamente",
                "pago_id": pago.id
            })
        
        return Response({
            "status": "error",
            "message": f"El pago no fue aprobado. Estado: {payment_status}"
        }, status=status.HTTP_400_BAD_REQUEST)


class RegistrarPagoParcialView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Registra un pago parcial para un alquiler"""
        serializer = PagoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        alquiler = get_object_or_404(Alquiler, id=serializer.validated_data['alquiler_id'])
        monto = Decimal(serializer.validated_data['monto'])

        # Validar que el monto no exceda el saldo pendiente
        saldo_pendiente = alquiler.saldo_pendiente
        if monto >= saldo_pendiente:
            return Response(
                {"error": "Este endpoint es solo para pagos parciales. Use RegistrarPagoView para pagos completos."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            pago = Pago.objects.create(
                alquiler=alquiler,
                monto=monto,
                metodo_pago=serializer.validated_data['metodo_pago'],
                estado_pago='parcial',
                referencia_transaccion=serializer.validated_data.get('referencia_transaccion', ''),
                aprobado_por=request.user,
                fecha_vencimiento=timezone.now().date() + timedelta(days=2)
            )
            enviar_notificacion_pago(pago, request.user)
            return Response(PagoDetalleSerializer(pago).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": f"Error al registrar el pago parcial: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
class TotalPagadoAlquilerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, alquiler_id):
        """
        Obtiene el total pagado para un alquiler específico
        """
        alquiler = get_object_or_404(Alquiler, id=alquiler_id)
        
        # Calcular el total pagado sumando todos los pagos aprobados
        total_pagado = alquiler.pagos.filter(
            estado_pago__in=['pagado', 'parcial']
        ).aggregate(
            total=Sum('monto')
        )['total'] or Decimal('0.00')

        # Obtener el porcentaje pagado
        porcentaje_pagado = (total_pagado / alquiler.precio_total * 100) if alquiler.precio_total > 0 else 0

        return Response({
            'alquiler_id': alquiler.id,
            'total_pagado': total_pagado,
            'saldo_pendiente': alquiler.precio_total - total_pagado,
            'porcentaje_pagado': round(float(porcentaje_pagado), 2),
            'moneda': 'COP'  # Puedes hacer esto configurable
        })        