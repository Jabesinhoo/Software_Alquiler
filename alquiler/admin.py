from django.contrib import admin
from .models import Cliente, Equipo, Alquiler, Pago, Contrato

admin.site.register(Equipo)
admin.site.register(Alquiler)
admin.site.register(Pago)
admin.site.register(Contrato)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo_cliente', 'estado_verificacion', 'moroso', 'deuda_total')
    list_filter = ('moroso', 'estado_verificacion', 'tipo_cliente')
    search_fields = ('nombre', 'numero_documento', 'email', 'nit')
    readonly_fields = ('dias_mora', 'deuda_total', 'fecha_marcado_moroso')
    fieldsets = (
        ('Información Básica', {
            'fields': ('foto', 'nombre', 'email', 'telefono', 'tipo_cliente')
        }),
        ('Documentación', {
            'fields': ('tipo_documento', 'numero_documento', 'nombre_empresa', 'nit')
        }),
        ('Ubicación', {
            'fields': ('direccion', 'ciudad', 'barrio')
        }),
        ('Estado y Preferencias', {
            'fields': ('estado_verificacion', 'metodo_pago_preferido', 'informacion_facturacion')
        }),
        ('Documentos', {
            'fields': ('documento_cedula', 'documento_rut', 'contrato_firmado', 'estudio_credito')
        }),
        ('Información de Morosidad', {
            'fields': ('moroso', 'dias_mora', 'deuda_total', 'fecha_marcado_moroso')
        }),
    )

from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin

# 🔹 Registrar usuarios y grupos en el admin
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, UserAdmin)
admin.site.register(Group, GroupAdmin)
