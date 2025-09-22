from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from ..models import Pago, Alquiler, Cliente
from decimal import Decimal

class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = [
            'monto',
            'metodo_pago',
            'estado_pago',
            'referencia_transaccion',
            'fecha_vencimiento',
            'comprobante_pago',
            'notas'
        ]
        widgets = {
            'alquiler': forms.Select(attrs={'class': 'form-control'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control'}),
            'metodo_pago': forms.Select(attrs={'class': 'form-control'}),
            'estado_pago': forms.Select(attrs={'class': 'form-control'}),
            'referencia_transaccion': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'comprobante_pago': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        alquiler = self.instance.alquiler  # Obtenemos el objeto alquiler

        if alquiler:
            max_saldo = alquiler.saldo_pendiente or Decimal('0.00')
            if max_saldo > 0:
                # Permitimos edición normal con límite máximo
                self.fields['monto'].widget.attrs.update({'max': max_saldo})
            else:
                # Bloqueamos edición si ya no hay saldo pendiente
                self.fields['monto'].widget.attrs.update({'readonly': True})

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        alquiler = self.instance.alquiler

        if alquiler:
            saldo_pendiente = alquiler.saldo_pendiente or Decimal('0.00')

            # Solo validamos cuando el saldo pendiente > 0
            if saldo_pendiente > 0 and monto is not None and monto > saldo_pendiente:
                raise forms.ValidationError(
                    f"El monto no puede ser mayor al saldo pendiente (${saldo_pendiente})"
                )

        return monto

class PagoParcialForm(PagoForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.alquiler:
            max_saldo = self.instance.alquiler.saldo_pendiente if self.instance.alquiler.saldo_pendiente is not None else Decimal('0.00')
            self.fields['monto'].widget.attrs.update({'max': max_saldo})


class AprobarPagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ['estado_pago', 'notas']


class FiltroPagosForm(forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.all(),
        required=False,
        label='Filtrar por Cliente'
    )
    estado = forms.ChoiceField(
        choices=Pago.ESTADO_PAGO,
        required=False,
        label='Filtrar por Estado'
    )
    fecha_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='Desde'
    )
    fecha_fin = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='Hasta'
    )