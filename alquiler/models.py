from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.conf import settings
import os
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Q, Sum
from django.templatetags.static import static
from django.db.models.functions import Coalesce
from datetime import timedelta  
from math import ceil
import base64
from io import BytesIO
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.core.files.base import ContentFile
from django.urls import reverse
from django.contrib.auth.models import Permission, Group
from django.db.models import F
from django.core.validators import FileExtensionValidator
from django.contrib.auth import get_user_model
import json
from django.db.models import F
import re
from django.core.serializers.json import DjangoJSONEncoder
import uuid

def equipo_foto_upload_path(instance, filename):
    """Función para definir la ruta de subida de fotos"""
    # Usamos el ID del equipo si no tiene número de serie
    if instance.numero_serie:
        return f'equipos/{instance.numero_serie}/{filename}'
    return f'equipos/{instance.id}/{filename}'


class Equipo(models.Model):
    uuid_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ESTADOS = [
        ('disponible', 'Disponible'),
        ('alquilado', 'En alquiler'),
        ('reservado', 'Reservado'),
        ('mantenimiento', 'En mantenimiento'),
    ]

    sku = models.CharField(
        max_length=50,
        unique=True,
        blank=True, 
        null=True,
        verbose_name="SKU",
        help_text="Código único de identificación del equipo"
    )
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    numero_serie = models.TextField(
        blank=True, 
        null=True,
        verbose_name="Números de serie",
        help_text="Ingrese múltiples números de serie separados por comas"
    )
    requiere_serie = models.BooleanField(default=True, verbose_name="Requiere número de serie")
    especificaciones = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='disponible')
    fecha_registro = models.DateField(auto_now_add=True)
    ubicacion = models.CharField(max_length=100)

    # Campos de inventario
    cantidad_total = models.PositiveIntegerField(default=1)
    cantidad_disponible = models.PositiveIntegerField(default=1)

    # Precios de alquiler
    precio_dia = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_semana = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    precio_mes = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    precio_trimestre = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    precio_semestre = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    precio_anio = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fecha_ultimo_alquiler = models.DateField(null=True, blank=True)

    # Descripción
    descripcion_larga = models.TextField(blank=True, null=True)
    es_html = models.BooleanField(default=False)
    valoracion_promedio = models.FloatField(default=0.0, validators=[MinValueValidator(0.0)])

    def numeros_serie_lista(self):
        """Devuelve los números de serie que están DISPONIBLES (no alquilados)"""
        if not self.numero_serie:
            return []

        todas_series = [s.strip() for s in self.numero_serie.split(',') if s.strip()]

        detalles_con_series = DetalleAlquiler.objects.filter(
            equipo=self,
            alquiler__estado_alquiler='activo'
        ).exclude(numeros_serie__isnull=True).exclude(numeros_serie__exact=[])

        series_alquiladas = []
        for detalle in detalles_con_series:
            if isinstance(detalle.numeros_serie, list):
                series_alquiladas.extend(detalle.numeros_serie)
            elif isinstance(detalle.numeros_serie, str):
                series_alquiladas.extend([s.strip() for s in detalle.numeros_serie.split(',') if s.strip()])

        return [s for s in todas_series if s not in series_alquiladas]

    def obtener_foto_principal(self):
        foto = self.fotos.filter(es_principal=True).first()
        if foto and foto.foto:
            return foto.foto.url
        return f"{settings.MEDIA_URL}equipos/default-equipo.png"

    def cantidad_numeros_serie(self):
        return len([s.strip() for s in self.numero_serie.split(',') if s.strip()]) if self.numero_serie else 0

    def agregar_numero_serie(self, nuevo_numero):
        nuevo_numero = nuevo_numero.strip()
        if not nuevo_numero:
            return False

        numeros = [s.strip() for s in self.numero_serie.split(',')] if self.numero_serie else []
        if nuevo_numero in numeros:
            return False

        numeros.append(nuevo_numero)
        self.numero_serie = ', '.join(numeros)
        self.actualizar_cantidades()
        self.save()
        return True

    def eliminar_numero_serie(self, numero):
        numero = numero.strip()
        numeros = [s.strip() for s in self.numero_serie.split(',')] if self.numero_serie else []
        if numero not in numeros:
            return False

        numeros.remove(numero)
        self.numero_serie = ', '.join(numeros) if numeros else None
        self.actualizar_cantidades()
        self.save()
        return True

    def actualizar_cantidades(self):
        cantidad_series = self.cantidad_numeros_serie()
        if cantidad_series > 0:
            self.cantidad_total = max(self.cantidad_total, cantidad_series)
            self.cantidad_disponible = max(0, self.cantidad_total)

    def actualizar_disponibilidad(self):
        """Actualiza la cantidad disponible basada en alquileres activos"""
        detalles_activos = DetalleAlquiler.objects.filter(
            equipo=self,
            alquiler__estado_alquiler='activo',
            alquiler__fecha_fin__gte=timezone.now().date()
        )

        cantidad_alquilada = 0
        for detalle in detalles_activos:
            if detalle.numeros_serie:
                if isinstance(detalle.numeros_serie, list):
                    cantidad_alquilada += len(detalle.numeros_serie)
                elif isinstance(detalle.numeros_serie, str):
                    series = [s.strip() for s in detalle.numeros_serie.split(',') if s.strip()]
                    cantidad_alquilada += len(series)
            else:
                cantidad_alquilada += detalle.cantidad

        self.cantidad_disponible = max(0, self.cantidad_total - cantidad_alquilada)

        if self.cantidad_disponible == 0:
            self.estado = 'alquilado'
        elif self.estado == 'alquilado' and self.cantidad_disponible > 0:
            self.estado = 'disponible'

        self.save()

    def proxima_fecha_disponible(self):
        if self.fecha_ultimo_alquiler:
            return self.fecha_ultimo_alquiler + timedelta(days=30)
        return None
    
    def get_absolute_url(self):
        return reverse('detalle_equipo', args=[str(self.id)])

    def __str__(self):
        series = self.numeros_serie_lista()
        serie_info = f" - {series[0]}" if series else ""
        if len(series) > 1:
            serie_info += f" (+{len(series)-1} más)"
        return f"{self.marca} {self.modelo}{serie_info} ({self.cantidad_disponible}/{self.cantidad_total})"

    class Meta:
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"
        ordering = ['marca', 'modelo']
        constraints = [
            models.CheckConstraint(
                check=models.Q(valoracion_promedio__gte=0.0) & models.Q(valoracion_promedio__lte=5.0),
                name="valoracion_promedio_rango"
            ),
            models.CheckConstraint(
                check=models.Q(cantidad_disponible__lte=models.F('cantidad_total')),
                name="cantidad_disponible_no_mayor_total"
            ),
            models.CheckConstraint(
                check=models.Q(precio_dia__gte=0),
                name="precio_dia_positivo"
            ),
            models.CheckConstraint(
                check=models.Q(cantidad_total__gte=0),
                name="cantidad_total_positiva"
            )
        ]


class UnidadEquipo(models.Model):
    equipo = models.ForeignKey(
        'Equipo',
        related_name='unidades',
        on_delete=models.CASCADE
    )


class FotoEquipo(models.Model):
    equipo = models.ForeignKey(
        'Equipo',  # en caso de que se defina más abajo
        related_name='fotos',
        on_delete=models.CASCADE,
        verbose_name="Equipo asociado"
    )
    foto = models.ImageField(
        upload_to='fotos_equipos/',  
        verbose_name="Archivo de imagen",
        help_text="Suba una foto del equipo",
        null=True, blank=True
    )
    es_principal = models.BooleanField(
        default=False,
        verbose_name="Foto principal",
        help_text="Marcar si esta es la foto principal del equipo"
    )
    fecha_subida = models.DateTimeField(auto_now_add=True)
    descripcion = models.CharField(max_length=255, blank=True, null=True)

    def save(self, *args, **kwargs):
        """Garantiza que solo haya una foto principal por equipo"""
        if self.es_principal and self.equipo_id:
            FotoEquipo.objects.filter(
                equipo=self.equipo,
                es_principal=True
            ).exclude(pk=self.pk).update(es_principal=False)

        super().save(*args, **kwargs)

    def __str__(self):
        desc = self.descripcion or 'Sin descripción'
        return f"Foto de {self.equipo.marca} {self.equipo.modelo} - {desc}"

    class Meta:
        verbose_name = "Foto de equipo"
        verbose_name_plural = "Fotos de equipos"
        ordering = ['-es_principal', 'fecha_subida']


class Cliente(models.Model):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    ESTADO_VERIFICACION = [
        ('pendiente', 'Pendiente'),
        ('verificado', 'Verificado'),
        ('rechazado', 'Rechazado'),
    ]

    TIPO_CLIENTE = [
        ('natural', 'Persona Natural'),
        ('juridica', 'Persona Jurídica'),
    ]

    TIPO_DOCUMENTO = [
        ('CC', 'Cédula de Ciudadanía'),
        ('CE', 'Cédula de Extranjería'),
        ('NIT', 'Número de Identificación Tributaria'),
        ('PAS', 'Pasaporte'),
    ]

    METODO_PAGO = [
        ('transferencia', 'Transferencia Bancaria'),
        ('nequi', 'Nequi'),
        ('daviplata', 'Daviplata'),
        ('tarjeta', 'Tarjeta de crédito/débito'),
        ('efectivo', 'Efectivo'),
    ]

    # Información general
    foto = models.ImageField(upload_to='fotos_clientes/', blank=True, null=True)
    nombre = models.CharField(max_length=100)
    email = models.EmailField()
    telefono = models.CharField(max_length=20)
    direccion = models.TextField()
    ciudad = models.CharField(max_length=50, blank=True, null=True)
    barrio = models.CharField(max_length=50, blank=True, null=True)

    # Identificación y tipo de cliente
    tipo_cliente = models.CharField(max_length=10, choices=TIPO_CLIENTE, default='Natural')
    tipo_documento = models.CharField(max_length=3, choices=TIPO_DOCUMENTO, default='CC')
    numero_documento = models.CharField(max_length=50, blank=True, null=True)

    # Empresa (si aplica)
    nombre_empresa = models.CharField(max_length=100, blank=True, null=True)
    nit = models.CharField(max_length=20, blank=True, null=True)

    # Preferencias y estado
    metodo_pago_preferido = models.CharField(max_length=30, choices=METODO_PAGO, blank=True, null=True)
    informacion_facturacion = models.TextField(blank=True, null=True)
    estado_verificacion = models.CharField(max_length=20, choices=ESTADO_VERIFICACION, default='pendiente')

    # Documentos
    documento_rut = models.FileField(upload_to='documentos/', blank=True, null=True)
    documento_cedula = models.FileField(upload_to='documentos/', blank=True, null=True)
    contrato_firmado = models.FileField(upload_to='contratos/', blank=True, null=True)
    estudio_credito = models.FileField(
        upload_to='estudios_credito/',
        blank=True,
        null=True,
        verbose_name="Estudio de crédito",
        help_text="Documento del estudio de crédito del cliente"
    )
    # Tiempos
    fecha_creacion = models.DateTimeField(auto_now_add=True, null=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    #Morosos
    moroso = models.BooleanField(default=False)
    fecha_marcado_moroso = models.DateField(null=True, blank=True)
    dias_mora = models.IntegerField(default=0)
    deuda_total = models.IntegerField(default=0)
    
    def get_absolute_url(self):
        return reverse('detalle_cliente', args=[str(self.id)])
    def __str__(self):
        return f"{self.nombre} ({self.numero_documento})"
    
    
class Alquiler(models.Model):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    ESTADO_ALQUILER = [
        ('activo', 'Activo'), ('finalizado', 'Finalizado'), ('cancelado', 'Cancelado'),
        ('reservado', 'Reservado'), ('pendiente_aprobacion', 'Pendiente de Aprobación'),
    ]
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='alquileres_creados', verbose_name="Creado por")
    cliente = models.ForeignKey('Cliente', on_delete=models.CASCADE, related_name='alquileres')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    # Asegúrate de que los valores por defecto sean Decimal
    precio_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    precio_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    fecha_vencimiento = models.DateField(blank=True, null=True)
    estado_alquiler = models.CharField(max_length=20, choices=ESTADO_ALQUILER, default='pendiente_aprobacion')
    renovacion = models.BooleanField(default=False)
    aprobado_por = models.CharField(max_length=100, blank=True, null=True)
    contrato_firmado = models.BooleanField(default=False)
    con_iva = models.BooleanField(default=False)
    renovacion_automatica = models.BooleanField(default=False)
    numero_factura = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Dejar en blanco para reservas")
    es_reserva = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{'Reserva' if self.es_reserva else 'Alquiler'} #{self.id} - {self.cliente}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('detalle_alquiler', args=[str(self.id)])

    def clean(self):
        if not self.es_reserva and not self.numero_factura:
            raise ValidationError("Debe ingresar un número de factura para alquileres activos.")
        if self.es_reserva:
            self.numero_factura = None

    def save(self, *args, **kwargs):
        if not self.es_reserva and not self.numero_factura and not self.renovacion:
            last = Alquiler.objects.filter(es_reserva=False, numero_factura__isnull=False).exclude(numero_factura='').order_by('-fecha_creacion').first()
            last_number = 0
            if last and last.numero_factura:
                match = re.search(r'FACT[-]?(\d+)', last.numero_factura)
                if match:
                    last_number = int(match.group(1))

            while True:
                nuevo_codigo = f"FACT-{last_number + 1:04d}"
                if not Alquiler.objects.filter(numero_factura=nuevo_codigo).exists():
                    self.numero_factura = nuevo_codigo
                    break
                last_number += 1

        self.full_clean()
        super().save(*args, **kwargs)

    def calcular_precio_total(self):
        if self.es_reserva or self.estado_alquiler == 'pendiente_aprobacion':
            self.precio_total = Decimal('0.00')
            self.save(update_fields=['precio_total'])
            return self.precio_total

        total = Decimal('0.00')
        for detalle in self.detalles.all():
            if detalle.precio_total is not None:
                total += detalle.precio_total
            elif detalle.precio_unitario is not None and detalle.precio_unitario > 0:
                precio = detalle.precio_unitario * detalle.cantidad
                precio_con_iva = (precio * Decimal('1.19')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                total += precio_con_iva

        self.precio_total = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.save(update_fields=['precio_total'])
        return self.precio_total

    def total_pagado(self):
        # Asegura que siempre se retorne un Decimal, incluso si no hay pagos.
        return self.pagos.all().aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    @property
    def saldo_pendiente(self):
        # Asegura que precio_total_val sea Decimal, y que total_pagado() también lo sea.
        precio_total_val = self.precio_total if self.precio_total is not None else Decimal('0.00')
        return precio_total_val - self.total_pagado()
    

class DetalleAlquiler(models.Model):
    PERIODO_CHOICES = [
        ('dia', 'Por día'),
        ('semana', 'Por semana'),
        ('mes', 'Por mes'),
        ('trimestre', 'Por trimestre'),
        ('semestre', 'Por semestre'),
        ('anio', 'Por año')
    ]
    
    alquiler = models.ForeignKey('Alquiler', on_delete=models.CASCADE, related_name='detalles')
    equipo = models.ForeignKey('Equipo', on_delete=models.PROTECT)
    numeros_serie = models.JSONField(default=list, blank=True, null=True)  # Opcional
    cantidad = models.PositiveIntegerField(default=1)
    periodo_alquiler = models.CharField(max_length=20, choices=PERIODO_CHOICES, default='dia')
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    precio_total = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    con_iva = models.BooleanField(default=True, verbose_name="Aplica IVA")

    def __str__(self):
        return f"{self.equipo} - {self.get_periodo_alquiler_display()}"

    def save(self, *args, **kwargs):
        if not self.numeros_serie:
            self.numeros_serie = []

        if len(self.numeros_serie) == 0 and not self.equipo.requiere_serie:
            self.cantidad = 1

        dias = (self.alquiler.fecha_fin - self.alquiler.fecha_inicio).days + 1
        precio_total_base = Decimal('0.00')

        if self.periodo_alquiler == 'dia':
            precio_total_base = self.precio_unitario * self.cantidad * dias
        elif self.periodo_alquiler == 'semana':
            semanas = max(1, ceil(dias / 7))
            precio_total_base = self.precio_unitario * self.cantidad * semanas
        elif self.periodo_alquiler == 'mes':
            meses = max(1, ceil(dias / 30))
            precio_total_base = self.precio_unitario * self.cantidad * meses
        elif self.periodo_alquiler == 'trimestre':
            trimestres = max(1, ceil(dias / 90))
            precio_total_base = self.precio_unitario * self.cantidad * trimestres
        elif self.periodo_alquiler == 'semestre':
            semestres = max(1, ceil(dias / 180))
            precio_total_base = self.precio_unitario * self.cantidad * semestres
        elif self.periodo_alquiler == 'anio':
            anios = max(1, ceil(dias / 365))
            precio_total_base = self.precio_unitario * self.cantidad * anios

        if self.con_iva:
            self.precio_total = (precio_total_base * Decimal('1.19')).quantize(Decimal('0.01'))
        else:
            self.precio_total = precio_total_base.quantize(Decimal('0.01'))

        super().save(*args, **kwargs)

        self.actualizar_disponibilidad_equipo()
        self.alquiler.calcular_precio_total()


    def actualizar_disponibilidad_equipo(self):
        if not self.pk:
        # Es un nuevo detalle → validar siempre
            validar = True
            cantidad_original = 0
        else:
            try:
                original = DetalleAlquiler.objects.get(pk=self.pk)
                validar = (
                    original.equipo_id != self.equipo_id
                    or original.cantidad != self.cantidad
                )
                cantidad_original = original.cantidad
            except DetalleAlquiler.DoesNotExist:
                validar = True
                cantidad_original = 0

        if not validar:
            return  # ❌ No hay cambios → no validamos

        equipo = self.equipo
        stock_virtual = equipo.cantidad_disponible + cantidad_original
        if self.cantidad > stock_virtual:
            raise ValidationError(
                f"No hay suficiente disponibilidad para el equipo {equipo.marca} {equipo.modelo} "
                f"(disponibles: {stock_virtual}, requeridos: {self.cantidad})"
            )




class Acta(models.Model):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    TIPO_ACTA = [
        ('entrega', 'Acta de Entrega'),
        ('devolucion', 'Acta de Devolución'),
    ]
    
    alquiler = models.ForeignKey('Alquiler', on_delete=models.CASCADE, related_name='actas')
    tipo = models.CharField(max_length=10, choices=TIPO_ACTA)
    archivo = models.FileField(
        upload_to='actas/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])]
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    numero_acta = models.CharField(max_length=20, unique=True, blank=True, null=True)
    
    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Acta'
        verbose_name_plural = 'Actas'
    
    def __str__(self):
        return f"Acta {self.get_tipo_display()} - Alquiler {self.alquiler.id}"
    
    def save(self, *args, **kwargs):
        if not self.numero_acta:
            last = Acta.objects.order_by('-id').first()
            last_number = int(last.numero_acta.split('-')[1]) if last and last.numero_acta else 0
            self.numero_acta = f"ACT-{last_number + 1:04d}"
        super().save(*args, **kwargs)


class Pago(models.Model):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    ESTADO_PAGO = [
        ('pendiente', 'Pendiente'), ('pagado', 'Pagado'), ('parcial', 'Parcial'),
        ('vencido', 'Vencido'), ('rechazado', 'Rechazado'),
    ]
    METODOS = [
        ('tarjeta', 'Tarjeta de crédito/débito'), ('transferencia', 'Transferencia bancaria'),
        ('efectivo', 'Efectivo'), ('nequi', 'Nequi'), ('daviplata', 'Daviplata'),
        ('otros', 'Otro método electrónico'),
    ]

    alquiler = models.ForeignKey('Alquiler', on_delete=models.CASCADE, related_name='pagos', null=True, blank=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00')) # Añadir default
    fecha_pago = models.DateField(auto_now_add=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    metodo_pago = models.CharField(max_length=20, choices=METODOS)
    estado_pago = models.CharField(max_length=20, choices=ESTADO_PAGO, default='pendiente')
    factura_generada = models.BooleanField(default=False)
    referencia_transaccion = models.CharField(max_length=100, blank=True, null=True)
    comprobante_pago = models.FileField(upload_to='comprobantes/', blank=True, null=True)
    notas = models.TextField(blank=True, null=True)
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-fecha_pago']
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'

    def __str__(self):
        return f"Pago #{self.id} - {self.alquiler} - ${self.monto}"

    def clean(self):
        super().clean()

        monto_value = self.monto if self.monto is not None else Decimal('0.00')
        saldo_pendiente_value = Decimal('0.00')

        if self.alquiler and hasattr(self.alquiler, 'saldo_pendiente'):
            saldo_pendiente_value = self.alquiler.saldo_pendiente if self.alquiler.saldo_pendiente is not None else Decimal('0.00')

        if self.estado_pago == 'parcial' and monto_value >= saldo_pendiente_value and saldo_pendiente_value > Decimal('0.00'):
            raise ValidationError({'monto': "Un pago parcial no puede cubrir el saldo pendiente completo. Use estado 'pagado' en su lugar."})

    def save(self, *args, **kwargs):
        if not self.pk:
            if self.estado_pago == 'parcial' and self.alquiler and \
               self.alquiler.saldo_pendiente is not None and \
               self.monto == self.alquiler.saldo_pendiente:
                self.estado_pago = 'pagado'
        super().save(*args, **kwargs)

    def actualizar_estado_alquiler(self):
        alquiler = self.alquiler
        if not alquiler:
            return

        total_pagado = alquiler.pagos.filter(estado_pago__in=['pagado', 'parcial']).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

        if total_pagado >= alquiler.precio_total:
            alquiler.estado_alquiler = 'finalizado'
            alquiler.save(update_fields=['estado_alquiler'])
            alquiler.pagos.filter(estado_pago='parcial').update(estado_pago='pagado')
        elif total_pagado > 0:
            alquiler.estado_alquiler = 'activo'
            alquiler.save(update_fields=['estado_alquiler'])


class Contrato(models.Model):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    alquiler = models.OneToOneField('Alquiler', on_delete=models.CASCADE, related_name='contrato')
    fecha_contratacion = models.DateField(auto_now_add=True)
    fecha_firma = models.DateField(blank=True, null=True)
    firma_cliente = models.ImageField(upload_to='firmas/', blank=True, null=True)
    firma_representante = models.ImageField(upload_to='firmas_representante/', blank=True, null=True)
    documento_contrato = models.FileField(upload_to='contratos/', blank=True, null=True)
    terminos_contrato = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Contrato #{self.id} - Alquiler {self.alquiler.id}"
    
    def get_firma_base64(self, field_name):
        """Método genérico para obtener firma en base64"""
        firma_field = getattr(self, field_name, None)
        if firma_field:
            try:
                with firma_field.open('rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                print(f"Error al leer {field_name}: {str(e)}")
        return None
        
    def generar_documento_contrato(self):
        """Genera el PDF del contrato con las firmas incluidas"""
        try:
            context = {
                'alquiler': self.alquiler,
                'contrato': self,
                'fecha_actual': timezone.now().date(),
                'equipos': self.alquiler.detalles.all(),
                'firma_cliente_base64': self.get_firma_base64('firma_cliente'),
                'firma_representante_base64': self.get_firma_base64('firma_representante'),
                'numero_factura': self.alquiler.numero_factura

            }
            
            html = render_to_string('contrato_pdf.html', context)
            
            result = BytesIO()
            pdf_options = {
                'encoding': 'UTF-8',
                'quiet': True,
            }
            
            pisa_status = pisa.CreatePDF(
                html, 
                dest=result,
                link_callback=self.handle_links,
                **pdf_options
            )
            
            if not pisa_status.err:
                nombre_archivo = f"contrato_{self.alquiler.id}_{timezone.now().date()}.pdf"
                self.documento_contrato.save(
                    nombre_archivo, 
                    ContentFile(result.getvalue()), 
                    save=False
                )
                self.save()
                return True
            return False
            
        except Exception as e:
            print(f"Error al generar PDF: {str(e)}")
            return False
    
    def handle_links(self, uri, rel):
        """Manejador de recursos externos (como imágenes) para xhtml2pdf"""
        if uri.startswith('data:image'):
            return uri
        return None



class Rol(Group):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    descripcion = models.TextField(blank=True, verbose_name="Descripción")
    
    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_permissions_by_app(self):
        """Devuelve los permisos agrupados por aplicación"""
        return (
            self.permissions.all()
            .order_by('content_type__app_label', 'content_type__model', 'codename')
            .select_related('content_type')
        )

    def get_permission_summary(self):
        """Resumen legible de permisos"""
        perms = self.get_permissions_by_app()
        summary = {}
        for perm in perms:
            app_label = perm.content_type.app_label
            model_name = perm.content_type.model
            key = f"{app_label}.{model_name}"
            
            if key not in summary:
                summary[key] = {
                    'app_label': app_label,
                    'model_name': model_name,
                    'permissions': []
                }
            
            # Simplificar el nombre del permiso
            action = perm.codename.split('_')[0]
            summary[key]['permissions'].append({
                'id': perm.id,
                'name': perm.name,
                'action': action,
                'codename': perm.codename
            })
        return summary

    def get_app_labels(self):
        """Obtiene las apps distintas que tiene permisos este rol"""
        return (
            self.permissions.all()
            .values_list('content_type__app_label', flat=True)
            .distinct()
            .order_by('content_type__app_label')
        )

    def clean(self):
        """Validación personalizada"""
        if not self.name:
            raise ValidationError("El nombre del rol es obligatorio.")
        
        # Verificar que el nombre no exista (excluyendo este mismo objeto)
        if self.pk:
            if Rol.objects.filter(name=self.name).exclude(pk=self.pk).exists():
                raise ValidationError("Ya existe un rol con este nombre.")
        else:
            if Rol.objects.filter(name=self.name).exists():
                raise ValidationError("Ya existe un rol con este nombre.")

class UsuarioManager(BaseUserManager):
    def _create_user(self, nombre_usuario, password, **extra_fields):
        """Método base para creación de usuarios"""
        if not nombre_usuario:
            raise ValueError("El nombre de usuario es obligatorio.")
        
        # Asignación automática de rol cliente si no se especifica
        if 'rol' not in extra_fields:
            extra_fields['rol'], created = Rol.objects.get_or_create(
                name="cliente",
                defaults={'descripcion': 'Rol por defecto para clientes'}
            )
        
        user = self.model(nombre_usuario=nombre_usuario, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, nombre_usuario, password=None, **extra_fields):
        """Crea un usuario regular con rol cliente por defecto"""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(nombre_usuario, password, **extra_fields)

    def create_superuser(self, nombre_usuario, password, **extra_fields):
        """Crea un superusuario con rol administrador"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        # Asignar rol de administrador
        extra_fields['rol'], created = Rol.objects.get_or_create(
            name="administrador",
            defaults={
                'descripcion': 'Administrador del sistema con todos los permisos',
            }
        )
        
        return self._create_user(nombre_usuario, password, **extra_fields)

class Usuario(AbstractBaseUser, PermissionsMixin):
    uuid_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    nombre_usuario = models.CharField(
        max_length=100, 
        unique=True,
        verbose_name="Nombre de usuario"
    )
    estado_usuario = models.CharField(
        max_length=20, 
        default='activo',
        verbose_name="Estado"
    )
    ultimo_acceso = models.DateTimeField(
        auto_now=True,
        verbose_name="Último acceso"
    )
    rol = models.ForeignKey(
        Rol, 
        on_delete=models.PROTECT,
        verbose_name="Rol asignado",
        related_name="usuarios"
    )
    cliente = models.OneToOneField(
        'Cliente', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Cliente asociado"
    )
    activation_token = models.CharField(
        max_length=50, 
        blank=True, 
        null=True,
        verbose_name="Token de activación"
    )
    activation_token_created = models.DateTimeField(
        blank=True, 
        null=True,
        verbose_name="Fecha creación token"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )
    is_staff = models.BooleanField(
        default=False,
        verbose_name="Acceso administración"
    )

    objects = UsuarioManager()

    USERNAME_FIELD = 'nombre_usuario'

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ['nombre_usuario']

    def __str__(self):
        return self.nombre_usuario

    def save(self, *args, **kwargs):
        """Asigna automáticamente el rol de cliente si no tiene rol asignado"""
        creating = self.pk is None
        
        if not self.rol_id:
            self.rol, created = Rol.objects.get_or_create(
                name="cliente",
                defaults={'descripcion': 'Rol por defecto para clientes'}
            )
        
        # Guardar el usuario primero
        super().save(*args, **kwargs)
        
        # Sincronizar grupos con el rol
        self.groups.clear()
        if self.rol:
            self.groups.add(self.rol)

    @property
    def has_admin_access(self):
        """Determina si el usuario tiene acceso administrativo"""
        return self.is_staff or self.is_superuser
    
    @property
    def username(self):
        """Propiedad para compatibilidad con código que espere el campo username"""
        return self.nombre_usuario
    
    def get_role_permissions(self):
        """Obtiene los permisos del rol del usuario"""
        if hasattr(self, 'rol'):
            return self.rol.get_permission_summary()
        return {}

    def clean(self):
        """Validación personalizada"""
        if not self.nombre_usuario:
            raise ValidationError("El nombre de usuario es obligatorio.")
        
        # Verificar que el nombre de usuario no exista (excluyendo este mismo usuario)
        if self.pk:
            if Usuario.objects.filter(nombre_usuario=self.nombre_usuario).exclude(pk=self.pk).exists():
                raise ValidationError("Ya existe un usuario con este nombre.")
        else:
            if Usuario.objects.filter(nombre_usuario=self.nombre_usuario).exists():
                raise ValidationError("Ya existe un usuario con este nombre.")


class UserAuditLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Inicio de sesión'),
        ('login_failed', 'Intento fallido de login'),
        ('logout', 'Cierre de sesión'),
        ('password_change', 'Cambio de contraseña'),
        ('password_reset', 'Restablecimiento de contraseña'),
        ('user_edit', 'Edición de perfil'),
        ('user_create', 'Creación de usuario'),
        ('user_delete', 'Eliminación de usuario'),
        ('role_change', 'Cambio de rol'),
        ('status_change', 'Cambio de estado'),
        ('permission_change', 'Cambio de permisos'),
        ('data_access', 'Acceso a datos sensibles'),
        ('config_change', 'Cambio de configuración'),
        ('export_data', 'Exportación de datos'),
        ('admin_action', 'Acción administrativa'),
    ]

    STATUS_CHOICES = [
        ('success', 'Exitoso'),
        ('failed', 'Fallido'),
        ('warning', 'Advertencia'),
    ]

    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name='audit_logs',
        verbose_name='Usuario'
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        verbose_name='Acción'
    )
    ip_address = models.GenericIPAddressField(
        verbose_name='Dirección IP'
    )
    user_agent = models.TextField(
        blank=True,
        null=True,
        verbose_name='Agente de usuario'
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        verbose_name='Fecha y hora'
    )
    details = models.JSONField(
        encoder=DjangoJSONEncoder,
        default=dict,
        verbose_name='Detalles'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='success',
        verbose_name='Estado'
    )
    target_user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='affected_by_actions',
        verbose_name='Usuario objetivo'
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Registro de auditoría'
        verbose_name_plural = 'Registros de auditoría'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'status']),
        ]

    def __str__(self):
        return f"{self.get_action_display()} - {self.user} ({self.timestamp})"

    def get_details_display(self):
        """Formatea los detalles para visualización"""
        if not isinstance(self.details, dict):
            return "Sin detalles"
        
        details = []
        if self.details.get('browser'):
            details.append(f"Navegador: {self.details['browser']}")
        if self.details.get('os'):
            details.append(f"Sistema operativo: {self.details['os']}")
        if 'is_mobile' in self.details:
            details.append(f"Dispositivo: {'Móvil' if self.details['is_mobile'] else 'Escritorio'}")
        if self.details.get('path'):
            details.append(f"Ruta: {self.details['path']}")
        if self.details.get('method'):
            details.append(f"Método: {self.details['method']}")
        if self.details.get('status_code'):
            details.append(f"Código de estado: {self.details['status_code']}")
        
        return "\n".join(details) if details else "Sin detalles"

    def get_export_data(self):
        """Prepara los datos para exportación"""
        details = self.details if isinstance(self.details, dict) else {}
        return {
            'fecha_hora': self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'accion': self.get_action_display(),
            'estado': self.get_status_display(),
            'ip': self.ip_address,
            'navegador': details.get('browser', 'Desconocido'),
            'sistema_operativo': details.get('os', 'Desconocido'),
            'dispositivo': 'Móvil' if details.get('is_mobile') else 'Escritorio',
            'usuario_objetivo': str(self.target_user) if self.target_user else 'N/A',
            'detalles': self.get_details_display()
        }