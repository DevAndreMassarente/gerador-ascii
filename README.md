# Gerador ASCII 2.0

Converta imagens em arte para terminal, texto UTF-8 ou HTML independente. O
Gerador ASCII combina ajuste de proporção, presets de imagem, dithering, cores
ANSI e três renderizadores: ASCII clássico, half-block e Braille.

O projeto lê os formatos raster suportados pela instalação do Pillow, corrige a
orientação EXIF, preserva transparência e também permite escolher um frame de
GIF, APNG ou WebP animado.

## Destaques

- ASCII com charsets prontos ou personalizados.
- Half-block com `▀`, `▄` e `█`: até dois pixels verticais por célula.
- Braille Unicode: matriz de 2 × 4 pontos por célula.
- Sem cor, uma cor ou as cores da imagem.
- ANSI truecolor, 256 cores e 16 cores.
- Dithering Floyd–Steinberg e ordenado.
- Presets para fotos, logos e desenhos de linha.
- Saída em texto, ANSI ou página HTML autocontida.
- Entrada por arquivo ou `stdin`.
- Escrita atômica, proteção contra sobrescrita e limites de recursos.

## Requisitos e instalação

- Python 3.10 ou mais recente.
- Pillow 10 ou mais recente.

Em um clone do projeto:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Isso instala o comando `gerador-ascii`:

```bash
gerador-ascii --version
gerador-ascii --help
```

Também é possível executar o módulo diretamente:

```bash
python image2ascii.py --help
```

Para desenvolvimento:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

## Uso rápido

Sem opções, a largura é 100 colunas e a altura é calculada pela proporção da
imagem:

```bash
gerador-ascii imagem.png
```

Defina uma grade completa com o argumento `COLUNASxLINHAS`:

```bash
gerador-ascii foto.jpg 100x40
```

Ou informe somente uma dimensão e deixe a outra ser calculada:

```bash
gerador-ascii foto.jpg --width 120
gerador-ascii foto.jpg --height 35
```

`COLUNASxLINHAS`/`--size` e `--width`/`--height` são alternativas; não devem ser
usados juntos.

## Modos de renderização

### ASCII

É o modo padrão. Cada pixel reduzido é convertido em um caractere de acordo com
sua densidade.

```bash
gerador-ascii retrato.jpg 100x42 --mode ascii --style photo
```

Charsets disponíveis:

- `dense`: muitos níveis, ideal para fotos e gradientes.
- `standard`: conjunto clássico e equilibrado.
- `simple`: menos caracteres e leitura limpa.
- `minimal`: visual mais gráfico.
- `blocks`: usa `░▒▓█`.
- `binary`: somente espaço e `@`.

O charset automático acompanha o preset: `dense` em `normal` e `photo`, e
`standard` em `logo` e `lineart`. Uma escolha explícita sempre vence:

```bash
gerador-ascii imagem.png 90x30 --charset minimal
gerador-ascii imagem.png 90x30 --chars ' .oO@'
```

Em `--chars`, informe os glifos do vazio para o mais denso. São necessários ao
menos dois caracteres, todos com uma coluna de largura. Controles, sequências
ANSI, caracteres combinantes e glifos largos são recusados. `--chars` só se
aplica ao modo ASCII.

### Half-block

Usa a metade superior e inferior de cada célula, dobrando a resolução vertical
efetiva. É especialmente eficiente com as cores originais:

```bash
gerador-ascii foto.jpg 100x35 --mode halfblock --color-mode image
```

Terminais sem cor ainda podem usar `▀`, `▄` e `█` como representação binária:

```bash
gerador-ascii silhueta.png 80x30 --mode halfblock --color-mode none
```

### Braille

Cada caractere Braille representa uma matriz de 2 × 4 pontos. O modo funciona
bem para ilustrações, mapas, contornos e detalhes finos:

```bash
gerador-ascii desenho.png 90x30 --mode braille --style lineart
gerador-ascii desenho.png 90x30 --mode braille --braille-threshold 110
```

A saída usa Unicode; escolha uma fonte de terminal que contenha os glifos
Braille.

## Presets e ajuste fino

`--style` seleciona valores coerentes de contraste, brilho, gamma e reforço de
contornos:

| Preset | Contraste | Brilho | Gamma | Contornos | Uso sugerido |
| --- | ---: | ---: | ---: | ---: | --- |
| `normal` | 1.10 | 1.00 | 1.00 | 0.12 | uso geral |
| `photo` | 1.05 | 1.00 | 1.00 | 0.06 | fotografias e gradientes |
| `logo` | 1.28 | 1.00 | 0.95 | 0.22 | logos e formas sólidas |
| `lineart` | 1.42 | 1.02 | 0.90 | 0.34 | traços e alto contraste |

Cada valor pode ser sobrescrito individualmente:

```bash
gerador-ascii foto.jpg 110x45 \
  --style photo --contrast 1.2 --brightness 1.05 --gamma 0.9 --edges 0.15
```

Outros controles úteis:

- `--threshold 0..255`: remove densidades muito baixas no ASCII.
- `--halfblock-threshold 0..255`: define quais pixels do half-block ficam
  ativos nos modos `none` e `mono`.
- `--braille-threshold 0..255`: define quais pontos Braille ficam ativos.
- `--alpha-threshold 0..255`: descarta pixels transparentes ou quase
  transparentes.
- `--polarity auto|dark|light`: informa a polaridade do fundo.
- `--invert`: inverte a densidade resultante.
- `--no-auto-invert`: desliga a detecção automática de fundo.

### Proporção e enquadramento

O padrão `--aspect 0.50` compensa o fato de caracteres de terminal normalmente
serem mais altos que largos. Ajuste-o se a fonte deixar a arte achatada ou
esticada.

`--fit` controla como a imagem ocupa uma grade com largura e altura definidas:

- `contain`: preserva a imagem inteira e adiciona margens; é o padrão.
- `cover`: preserva a proporção e recorta o centro para preencher a grade.
- `stretch`: preenche toda a grade, mesmo que deforme a imagem.

## Dithering

O dithering cria padrões de pontos para representar tons que não existem no
conjunto de saída:

- `none`: quantização limpa; melhor para logos e arte já contrastada.
- `floyd-steinberg`: difusão de erro; produz gradientes suaves e orgânicos.
- `ordered`: matriz ordenada 4 × 4; textura estável e previsível.

Exemplos:

```bash
gerador-ascii foto.jpg 110x45 --style photo --dither floyd-steinberg
gerador-ascii desenho.png 90x30 --mode braille --dither ordered
gerador-ascii logo.png 70x25 --mode halfblock --color-mode mono --dither ordered
```

No ASCII, o dithering atua entre os níveis do charset. No Braille e nos modos
binários, ele decide quais pontos ficam acesos. No half-block com
`--color-mode image`, cada metade visível preserva diretamente a cor amostrada.
Por isso, nesse caminho específico, `--style`, ajustes tonais, `--invert`,
`--dither` e `--halfblock-threshold` não alteram os pixels; use `none` ou `mono`
quando quiser que a luminância controle quais metades são ativadas.

## Cores

`--color-mode` aceita:

- `none`: sem sequências de cor; é o padrão.
- `mono`: usa a cor de `--mono-color`.
- `image`: preserva as cores amostradas da imagem.

```bash
# Uma cor constante
gerador-ascii logo.png 80x28 --color-mode mono --mono-color '#ff365d'

# Uma tonalidade com intensidade variável
gerador-ascii logo.png 80x28 --color-mode mono \
  --mono-color 'rgb(80,200,255)' --mono-shading

# Cores originais
gerador-ascii foto.jpg 100x40 --color-mode image
```

Nomes de cores reconhecidos pelo Pillow, HEX e `rgb(...)` são aceitos.

`--ansi` define a precisão quando a saída é ANSI:

- `truecolor`: RGB de 24 bits; é o padrão.
- `ansi256`: paleta xterm de 256 cores.
- `ansi16`: paleta básica de 16 cores.

```bash
gerador-ascii foto.jpg 100x40 --color-mode image --ansi ansi256
```

Para imagens transparentes, `--background auto` escolhe uma base clara ou
escura. Também é possível fixá-la:

```bash
gerador-ascii logo.png 80x30 --background white --polarity light
gerador-ascii logo.png 80x30 --background '#10131a' --color-mode image
```

O terminal não informa sua cor de fundo de forma portável. Se cores escuras
sumirem em um terminal escuro (por exemplo, um logo preto composto sobre
branco), `--paint-background` pinta o matte em toda a grade ANSI:

```bash
gerador-ascii logo-preto.png 80x30 --color-mode image --paint-background
```

Essa opção preserva a grade retangular mesmo sem `--keep-trailing-spaces`. Sem
ela, o fundo do terminal continua transparente. HTML sempre incorpora o matte.

## Formatos de saída

`--format` aceita `auto`, `text`, `ansi` e `html`:

- `auto`: gera HTML para arquivos `.html`/`.htm`; nos demais casos usa ANSI se
  houver cor e texto simples se `--color-mode none`.
- `text`: mantém somente os glifos, sem cores ANSI.
- `ansi`: usa sequências de escape de terminal conforme `--ansi`.
- `html`: página UTF-8 autocontida, com cores e fundo incorporados.

A saída vai para `stdout` por padrão:

```bash
gerador-ascii imagem.png 80x30 --format text > arte.txt
gerador-ascii imagem.png 80x30 --color-mode image --format ansi > arte.ans
```

Use `-o` para gravar diretamente:

```bash
gerador-ascii imagem.png 80x30 --format text -o arte.txt
gerador-ascii imagem.png 100x40 --color-mode image -o arte.ans
```

Espaços à direita são removidos por padrão. Para manter a grade retangular,
adicione `--keep-trailing-spaces`.

### HTML

A extensão `.html` ativa o formato automaticamente. O resultado não depende de
JavaScript nem de arquivos externos:

```bash
gerador-ascii foto.jpg 120x45 --mode halfblock --color-mode image -o arte.html
```

Também é possível enviar HTML explicitamente para `stdout`:

```bash
gerador-ascii foto.jpg 120x45 --color-mode image --format html -o - > arte.html
```

## Entrada por stdin

Use `-` como imagem de entrada. Isso facilita pipelines e permite integrar o
gerador com downloaders, capturas ou outros processadores de imagem:

```bash
cat foto.png | gerador-ascii - 80x30 --color-mode image
cat logo.png | gerador-ascii - 70x25 --style logo --format text -o logo.txt
```

`-o -` também significa `stdout`. A imagem recebida por `stdin` é lida como dado
binário; mensagens e avisos continuam em `stderr`.

## Imagens animadas e frames

O programa gera uma arte estática por execução. Em GIF, APNG, WebP animado ou
outro formato multipágina reconhecido pelo Pillow, `--frame N` seleciona um
quadro usando índice iniciado em zero:

```bash
gerador-ascii animacao.gif 90x35 --frame 0
gerador-ascii animacao.gif 90x35 --frame 7 --color-mode image
```

O frame padrão é `0`. Quando a imagem possui vários frames, o programa informa a
quantidade e o índice utilizado; `--quiet` omite esse aviso. Um índice fora da
faixa produz erro em vez de voltar silenciosamente ao primeiro frame.

## Segurança e sobrescrita

Arquivos existentes **não são substituídos por padrão**:

```bash
gerador-ascii foto.jpg -o arte.txt
# uma segunda execução recusa substituir arte.txt
```

Use `--force` somente quando quiser substituir conscientemente o destino:

```bash
gerador-ascii foto.jpg -o arte.txt --force
```

A gravação em arquivo é feita primeiro em um temporário no mesmo diretório e só
depois publicada no destino. Mesmo com `--force`, o programa se recusa a usar a
própria imagem de entrada como saída, incluindo aliases detectáveis por link.

Há limites padrão contra uso acidental ou malicioso de recursos:

- imagem de entrada: até 80 milhões de pixels;
- cada dimensão da grade: até 10.000 células;
- renderização: até 2 milhões de amostras — 2 milhões de células ASCII,
  1 milhão de half-blocks ou 250 mil células Braille.

`--allow-large` remove os limites próprios do programa e pode consumir muita
memória, CPU, espaço em disco e buffer do terminal. Use-o apenas com entradas e
dimensões confiáveis; para viabilizar a leitura, essa opção também suspende o
limite de *decompression bomb* do Pillow durante a abertura da imagem.

Charsets personalizados também são validados para impedir controles de terminal
e quebras de linha. Ao processar arquivos não confiáveis, mantenha o Pillow
atualizado.

## Referência resumida

| Área | Opções |
| --- | --- |
| Tamanho | `COLSxROWS`, `-s/--size`, `-w/--width`, `-H/--height`, `--aspect`, `--fit`, `--allow-large` |
| Aparência | `--mode`, `--style`, `--charset`, `--chars`, `--dither`, `--polarity`, `--invert`, `--no-auto-invert` |
| Cores | `--color-mode`, `--mono-color`, `--mono-shading`, `--background`, `--ansi`, `--paint-background` |
| Ajuste fino | `--contrast`, `--brightness`, `--gamma`, `--edges`, `--threshold`, `--halfblock-threshold`, `--braille-threshold`, `--alpha-threshold` |
| Entrada/saída | `--frame`, `-o/--output`, `--format`, `--keep-trailing-spaces`, `--force`, `--quiet` |
| Geral | `--help`, `--version` |

Consulte `gerador-ascii --help` para os valores aceitos e a ajuda rápida.

## Galeria de comandos

```bash
# Foto detalhada em ASCII truecolor
gerador-ascii foto.jpg 120x48 --style photo \
  --dither floyd-steinberg --color-mode image

# Logo vermelho, centralizado e sem deformação
gerador-ascii logo.png 80x28 --style logo --fit contain \
  --color-mode mono --mono-color '#ff2d55'

# Terminal HD com duas amostras verticais por célula
gerador-ascii paisagem.webp 120x40 --mode halfblock \
  --fit cover --color-mode image --ansi truecolor

# Line art em Braille e texto puro
gerador-ascii desenho.png 100x35 --mode braille --style lineart \
  --dither ordered --format text

# Página HTML com fundo personalizado
gerador-ascii retrato.png 110x42 --color-mode image \
  --background '#111318' --format html -o retrato.html

# Frame de uma animação vindo de stdin
cat animacao.gif | gerador-ascii - 90x32 --frame 3 \
  --mode halfblock --color-mode image
```
