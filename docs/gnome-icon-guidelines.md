# Recursos visuales — GNOME HIG

Reglas para los SVG del proyecto. En caso de discrepancia manda la especificación
oficial: <https://developer.gnome.org/hig/>.

## Tipos de recurso

| Tipo | Lienzo | Uso |
|---|---|---|
| Icono de aplicación | 128 × 128 | Identidad de la app en GNOME Shell |
| Icono simbólico | 16 × 16 | Botones, menús, listas |
| Ilustración de hardware | 128 × 128 (convención del proyecto) | Fichas de dispositivo |

## Iconos simbólicos

- Documento de 16 × 16 con `viewBox="0 0 16 16"` y `width="16" height="16"`.
- Monocromáticos: `fill` en negro (`#2e3436`); GTK los recolorea.
- Usar formas rellenas, no trazos. GTK interpreta los simbólicos como máscaras:
  un `stroke` se convierte en una silueta sólida y se pierden los detalles.
  Los huecos se consiguen con subtrazados y `fill-rule="evenodd"`.
- Sin degradados, sin sombras, sin perspectiva.
- Trazos principales de 2 px; evitar 1 px salvo para detalles secundarios.
- Geometría ortogonal y alineada a la cuadrícula de 1 px (0.5 px para trazos de 2 px).
- Debe leerse en claro y oscuro; el espacio negativo también debe funcionar invertido.
- Reutilizar iconos existentes de GTK / Icon Library antes de dibujar uno nuevo.
- Nombre: `<accion>-symbolic.svg`.

## Iconos de aplicación

- Lienzo de 128 × 128, sin llenarlo por completo; base alineada a la línea guía.
- Una sola metáfora, relacionada con el nombre o la función.
- Estilo geométrico simple, profundidad discreta (perfil inferior más oscuro).
- Colores de la paleta GNOME; degradados solo en superficies curvas.
- Sin sombras fuera de la silueta; la sombra exterior la genera el escritorio.
- Fondo transparente.
- Debe reconocerse a 32, 64 y 128 px.
- Incluir versión simbólica con la misma metáfora.

## Ilustraciones de hardware (criterio del proyecto)

- Carcasas en grises de la paleta (`Light 1–5`, `Dark 1–5`).
- Color saturado reservado a las zonas de iluminación.
- Zonas LED con `id` estable (`led-0`, `led-1`, …) para poder recolorearlas.
- Un grupo por pieza: `casing`, `rotor`, `leds`.
- Misma escala visual y mismo ángulo para toda la colección.

## Estructura del SVG

- `viewBox` siempre presente; unidades en `px`.
- Objetos en capas nombradas (`inkscape:groupmode="layer"`, `inkscape:label`).
- Sin textos convertidos a trazado salvo que sean parte del dibujo.
- Sin metadatos de editor innecesarios ni imágenes embebidas.
- Nombres de archivo en minúsculas y guiones: `fan-ring.svg`.

## Paleta GNOME (referencia)

- Azul: `#99c1f1` `#62a0ea` `#3584e4` `#1c71d8` `#1a5fb4`
- Verde: `#8ff0a4` `#57e389` `#33d17a` `#2ec27e` `#26a269`
- Amarillo: `#f9f06b` `#f8e45c` `#f6d32d` `#f5c211` `#e5a50a`
- Naranja: `#ffbe6f` `#ffa348` `#ff7800` `#e66100` `#c64600`
- Rojo: `#f66151` `#ed333b` `#e01b24` `#c01c28` `#a51d2d`
- Púrpura: `#dc8add` `#c061cb` `#9141ac` `#813d9c` `#613583`
- Marrón: `#cdab8f` `#b5835a` `#986a44` `#865e3c` `#63452c`
- Claros: `#ffffff` `#f6f5f4` `#deddda` `#c0bfbc` `#9a9996`
- Oscuros: `#77767b` `#5e5c64` `#3d3846` `#241f31` `#000000`

## Validación

- Iconos: App Icon Preview y Symbolic Preview.
- Simbólicos en contexto: recoloración real en GTK, no solo vista previa en Inkscape.
- Verificar el SVG con `inkscape --query-all` y exportar a 16, 32, 64 y 128 px.
