"""TFT ST7735S 1.8 pol. (128 x 160) no ESP8266 NodeMCU/Wemos D1 mini.

Os numeros abaixo sao GPIO, nao os rotulos D da placa. SPI1 usa pinos fixos;
GPIO12 (D6/MISO) fica reservado e sem fio. VDD e BLK ao 3V3; GND ao GND.
"""

BOARD = "esp8266"
SPI_ID = 1
# ST7735S especifica ciclo minimo de 66ns; 10MHz oferece margem para fios.
SPI_BAUDRATE = 10_000_000
SCK_PIN = 14  # D5
MOSI_PIN = 13  # D7
RESET_PIN = 16  # D0
DC_PIN = 4  # D2
CS_PIN = 5  # D1

# 0/2 = retrato (128x160); 1/3 = paisagem (160x128).
ROTATION = 3  # Paisagem girada 180 graus para a montagem no PC.
# Offsets sao nas coordenadas da rotacao escolhida, nao dos pinos.
# Muitos modulos 1.8 usam 0,0; alguns "green tab" usam 1,2 em paisagem
# (ou 2,1 em retrato). Ajuste se a borda aparecer deslocada/cortada.
X_OFFSET = 0
Y_OFFSET = 0
BGR = True  # Troque para False se vermelho e azul estiverem invertidos.
INVERT = False  # Troque apenas se preto/branco ou cores ficarem negativos.

STALE_MS = 5_000
DRAW_INTERVAL_MS = 250
MAX_LINE_BYTES = 1_024
SERIAL_BYTES_PER_TICK = 256
LOOP_SLEEP_MS = 10
