from django.shortcuts import render, redirect, get_object_or_404
from ..models import Cliente, Alquiler, Pago
from ..forms import ClienteForm, PagoForm
from django.db.models import Count
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required,permission_required
from django.db.models import Sum, Q
from django.db import models

def es_admin(user):
    return user.is_authenticated and user.is_staff  # o user.is_superuser

@login_required
@permission_required('alquiler.view_cliente', raise_exception=True)
def listar_clientes(request):
    clientes = Cliente.objects.all()
    query = request.GET.get('q') 

    if query:

        clientes = clientes.filter(
            Q(nombre__icontains=query) |
            Q(numero_documento__icontains=query) |
            Q(email__icontains=query) |
            Q(telefono__icontains=query) |
            Q(ciudad__icontains=query) |
            Q(nit__icontains=query) 
        ).distinct() 

    return render(request, 'lista_clientes.html', {'clientes': clientes})

@login_required
@permission_required('alquiler.add_cliente', raise_exception=True)
def crear_cliente(request):
    if request.method == 'POST':
        form = ClienteForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('alquiler:listar_clientes')
        else:
            print("Errores de formulario:", form.errors)  # <--- Agrega esto
    else:
        form = ClienteForm()

    return render(request, 'crear_cliente.html', {'form': form})


@login_required
@permission_required('alquiler.change_cliente', raise_exception=True)
def editar_cliente(request, id):
    try:
        cliente = get_object_or_404(Cliente, uuid_id=id)
    except Exception as e:
        raise

    form = ClienteForm(request.POST or None, request.FILES or None, instance=cliente)

    if request.method == 'POST':
        print("[DEBUG] Método POST recibido")
        if form.is_valid():
            form.save()
            messages.success(request, "Cliente actualizado correctamente")
            return redirect('alquiler:listar_clientes')
        else:
            print(form.errors)

    return render(request, 'editar_cliente.html', {
        'form': form,
        'cliente': cliente
    })


@login_required
@permission_required('alquiler.view_cliente', raise_exception=True)
def detalle_cliente(request, id):
    cliente = get_object_or_404(Cliente, uuid_id=id)
    historial_alquileres = Alquiler.objects.filter(cliente=cliente)
    pagos_pendientes = Pago.objects.filter(alquiler__cliente=cliente, estado_pago='pendiente')

    context = {
        'cliente': cliente,
        'historial_alquileres': historial_alquileres,
        'pagos_pendientes': pagos_pendientes
    }
    return render(request, 'detalle_cliente.html', context)


@login_required
@permission_required('alquiler.change_cliente', raise_exception=True)
def cambiar_estado_verificacion(request, id, nuevo_estado):
    cliente = get_object_or_404(Cliente, uuid_id=id)
    cliente.estado_verificacion = nuevo_estado
    cliente.save()
    return redirect('alquiler:detalle_cliente', id=cliente.uuid_id)


@login_required
@permission_required('alquiler.change_cliente', raise_exception=True)
def bloquear_cliente(request, id):
    cliente = get_object_or_404(Cliente, uuid_id=id)
    cliente.estado_verificacion = 'rechazado'
    cliente.save()
    messages.warning(request, f'El cliente {cliente.nombre} ha sido bloqueado.')
    return redirect('alquiler:detalle_cliente', id=cliente.uuid_id)

@login_required
@permission_required('alquiler.view_cliente', raise_exception=True)
def clientes_morosos(request):

    clientes = Cliente.objects.filter(moroso=True).prefetch_related(
        'alquileres__pagos'
    )

    for cliente in clientes:
        if cliente.fecha_marcado_moroso:
            cliente.dias_mora_calculado = (timezone.now().date() - cliente.fecha_marcado_moroso).days
        else:
            cliente.dias_mora_calculado = 0

        cliente.alquileres_morosos = Alquiler.objects.filter(
            cliente=cliente,
            pagos__estado_pago__in=['pendiente', 'parcial'],
            pagos__fecha_vencimiento__lte=timezone.now().date() - timedelta(days=2)
        ).distinct()

    clientes = sorted(clientes, key=lambda c: c.dias_mora_calculado, reverse=True)

    return render(request, 'clientes_morosos.html', {
        'clientes': clientes,
        'hoy': timezone.now().date()
    })


@login_required
@permission_required('alquiler.change_cliente', raise_exception=True)
def marcar_como_moroso(request, cliente_id):
    cliente = get_object_or_404(Cliente, uuid_id=cliente_id)
    
    if request.method == 'POST':
        cliente.moroso = True
        cliente.fecha_marcado_moroso = timezone.now().date()
        cliente.save()
        
        messages.warning(request, f'{cliente.nombre} ha sido marcado como moroso')
        return redirect('alquiler:detalle_cliente', id=cliente.uuid_id)
    
    return render(request, 'confirmar_moroso.html', {'cliente': cliente})

@login_required
def actualizar_morosidad_clientes():
    # Fecha límite para considerar moroso (15 días de gracia)
    fecha_limite_moroso = timezone.now().date() - timedelta(days=2)
    
    # 1. Identificar clientes que deben ser marcados como morosos
    clientes_con_pagos_vencidos = Cliente.objects.filter(
        Q(alquileres__pagos__estado_pago__in=['pendiente', 'parcial']) &
        Q(alquileres__pagos__fecha_vencimiento__lte=fecha_limite_moroso)
    ).distinct()
    
    # 2. Actualizar clientes morosos
    for cliente in clientes_con_pagos_vencidos:
        # Obtener el pago más atrasado
        pago_mas_atrasado = Pago.objects.filter(
            alquiler__cliente=cliente,
            estado_pago__in=['pendiente', 'parcial']
        ).order_by('fecha_vencimiento').first()
        
        if pago_mas_atrasado:
            dias_mora = (timezone.now().date() - pago_mas_atrasado.fecha_vencimiento).days
            
            # Calcular deuda total (suma de todos los pagos pendientes/parciales)
            deuda_total = Pago.objects.filter(
                alquiler__cliente=cliente,
                estado_pago__in=['pendiente', 'parcial']
            ).aggregate(total=Sum('monto'))['total'] or 0
            
            cliente.moroso = True
            cliente.dias_mora = dias_mora
            cliente.deuda_total = deuda_total
            cliente.fecha_marcado_moroso = timezone.now().date()
            cliente.save()
    
    # 3. Limpiar clientes que ya no son morosos (pagaron sus deudas)
    clientes_que_pagaron = Cliente.objects.filter(
        moroso=True
    ).exclude(
        id__in=clientes_con_pagos_vencidos.values('id')
    )
    
    for cliente in clientes_que_pagaron:
        cliente.moroso = False
        cliente.dias_mora = 0
        cliente.deuda_total = 0
        cliente.fecha_marcado_moroso = None
        cliente.save()

@login_required
@permission_required('alquiler.change_cliente', raise_exception=True)
def validar_documentos_cliente(request, id):
    cliente = get_object_or_404(Cliente, uuid_id=id)
    documentos_completos = cliente.documento_rut and cliente.documento_cedula

    if documentos_completos:
        cliente.estado_verificacion = 'verificado'
        cliente.save()
        messages.success(request, "Cliente validado correctamente.")
    else:
        messages.error(request, "Faltan documentos por subir.")

    return redirect('alquiler:detalle_cliente', id=cliente.uuid_id)

