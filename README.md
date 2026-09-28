# Monitor Linux · ESP8266 NodeMCU V3 + TFT ST7735

Monitor de sistema por USB para **ESP8266 NodeMCU V3 com TFT ST7735 de 1,8″, 128 × 160 pixels**. O Linux coleta as métricas e o ESP8266 desenha o painel na horizontal, em 160 × 128. Não precisa de Wi-Fi.

- CPU e RAM com barras de utilização.
- Temperatura da CPU e ocupação do sistema de arquivos escolhido.
- Utilização/temperatura de GPU NVIDIA ou AMD, quando disponíveis.
- Recebimento e envio de rede, tempo ligado, nome do computador e relógio.
- Aviso de dados desatualizados quando o coletor para; reconexão USB automática.

O ESP8266 funciona como uma tela: **o coletor precisa rodar no computador Linux que será monitorado**. Executar o coletor no WSL mostra as métricas do WSL.

## Começar no CachyOS com a placa já gravada

Se a tela já mostra **TFT MONITOR / aguardando USB**, conecte o ESP8266 ao PC e execute no CachyOS:

```bash
sudo pacman -S --needed git
git clone https://github.com/alestanalves/esp8266-linux-monitor.git
cd esp8266-linux-monitor
sudo bash scripts/install-cachyos.sh
```

Se o repositório estiver privado, a conta usada para clonar precisa ter acesso. Também é possível baixar **Code → Download ZIP** na página do GitHub, extrair, abrir um terminal nessa pasta e executar o instalador.

O instalador prepara as dependências e inicia o coletor agora e **sempre que o PC ligar, sem precisar fazer login**. A tela recebe uma amostra por segundo. Se a placa estiver desconectada durante o boot, o coletor aguarda e conecta quando ela aparecer; também tenta reconectar depois de retirar e recolocar o USB.

```bash
systemctl status tft-monitor --no-pager
journalctl -u tft-monitor -f
```

`Ctrl+C` fecha a visualização dos logs; o serviço continua funcionando. Para montar uma placa nova, siga as etapas abaixo. Para outros Linux, instale as dependências da etapa 1 e use o instalador genérico da etapa 5. O firmware atual é para **ESP8266**, e não para ESP32 ou Raspberry Pi Pico.

Para caber na RAM do ESP8266, o painel usa uma paleta de 16 cores e um framebuffer de 10.240 bytes. O driver converte uma linha por vez para RGB565 ao enviar à tela, mantendo as cores do painel sem reservar um framebuffer de 40.960 bytes.

## Ligações

Materiais: uma NodeMCU V3 com ESP8266, uma TFT SPI ST7735 de 1,8″ (128 × 160), oito fios jumper e um cabo USB de dados compatível com a placa. O computador Linux alimenta e se comunica com a NodeMCU por esse cabo.

Alimente a tela em **3,3 V**. Os nomes SCL/SDA deste módulo representam SPI. Desconecte a alimentação para refazer as ligações. A tabela mostra tanto o **nome Dn impresso na NodeMCU** quanto o **número GPIO usado pelo MicroPython**. Por exemplo, D5 é GPIO14; não é GPIO5. Esta é a pinagem configurada para a NodeMCU V3; refaça as ligações da tela conforme ela.

| TFT | NodeMCU V3 | GPIO | Função |
| --- | --- | --- | --- |
| GND | GND | — | Terra |
| VDD | 3V3 | — | Alimentação |
| SCL | D5 | GPIO14 | SPI SCK |
| SDA | D7 | GPIO13 | SPI MOSI |
| RST | D0 | GPIO16 | Reset da tela |
| DC | D2 | GPIO4 | Data/Command |
| CS | D1 | GPIO5 | Chip Select |
| BLK | 3V3 | — | Backlight |

O RST da tela vai ao **D0**, não ao pino RST da NodeMCU. O SPI usa os pinos fixos do ESP8266: D5/SCK e D7/MOSI; D6/GPIO12 é MISO e fica sem ligação à tela. O backlight fica aceso enquanto houver alimentação; conectado diretamente ao 3V3, não há controle de brilho por software. O cabo USB precisa transmitir dados. Consulte a [referência oficial de SPI do ESP8266](https://docs.micropython.org/en/latest/esp8266/quickref.html#hardware-spi-bus).

## 1. Preparar o projeto no Linux

O coletor precisa de **Python 3.10 ou superior**, `venv`, `pip` e acesso à porta USB serial. Instale as dependências correspondentes à sua distribuição. Os pacotes de compilação permitem instalar dependências como `psutil` caso não exista uma distribuição binária para seu sistema.

**CachyOS / Arch Linux:**

```bash
sudo pacman -S --needed git python python-pip base-devel
```

**Ubuntu / Debian / Linux Mint recentes:**

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip python3-dev build-essential
```

**Fedora:**

```bash
sudo dnf install git python3 python3-pip python3-devel gcc
```

**openSUSE com Python 3.10 ou superior:**

```bash
sudo zypper install git python3 python3-pip python3-devel gcc
```

Confira `python3 --version`. Algumas versões antigas do openSUSE Leap e de outras distribuições usam Python anterior a 3.10; nesse caso, use uma instalação mais recente do Python com seus pacotes `pip` e desenvolvimento correspondentes. Consulte as [instruções por distribuição do Python Packaging Guide](https://packaging.python.org/en/latest/guides/installing-using-linux-tools/) e o [pacote venv do Debian](https://packages.debian.org/bookworm/python3-venv).

Baixe o projeto se ainda não o fez:

```bash
git clone https://github.com/alestanalves/esp8266-linux-monitor.git
cd esp8266-linux-monitor
```

Na pasta do projeto, prepare o ambiente Python local:

```bash
bash scripts/setup.sh
.venv/bin/tft-monitor --once
```

O último comando imprime uma amostra real de métricas em JSON, sem precisar da placa. Para acompanhar continuamente pelo terminal, use `--dump`. O script instala o coletor, as ferramentas de gravação e as dependências de testes dentro de `.venv`; não precisa de `sudo`.

As instruções de outras distribuições são orientações de instalação; não representam testes físicos em todas elas. O registro de testes está em [VALIDACAO.md](docs/VALIDACAO.md). O coletor pode ser executado manualmente em Linux sem systemd; a instalação automática fornecida exige systemd ativo.

### Permissões USB

Antes de gravar ou monitorar a placa, configure o acesso à USB e reconecte o ESP8266. Estas regras dão acesso à sessão local ativa e ao usuário do serviço:

```bash
getent group tft-monitor || sudo groupadd --system tft-monitor
sudo install -d -m 0755 /etc/udev/rules.d
sudo install -m 0644 systemd/70-tft-monitor.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty --action=change
```

Em uma sessão SSH sem acesso local, confira o grupo com `ls -l /dev/ttyUSB0`, adicione seu usuário ao grupo apropriado e entre novamente. Não é necessário executar o coletor como root.

## 2. Instalar MicroPython no ESP8266

Se a placa já tem MicroPython recente, siga para a próxima etapa. Para a **NodeMCU V3**, baixe a versão padrão `.bin` de [ESP8266_GENERIC](https://micropython.org/download/ESP8266_GENERIC/) para placas com pelo menos 2 MiB de flash e confira o chip:

```bash
.venv/bin/python -m esptool --chip esp8266 --port /dev/ttyUSB0 flash-id
```

Antes da primeira instalação, salve uma cópia completa da flash. Ajuste `0x400000` ao tamanho informado por `flash-id` (este exemplo é para 4 MiB):

```bash
mkdir -p backups
.venv/bin/python -m esptool --chip esp8266 --port /dev/ttyUSB0 read-flash 0 0x400000 backups/esp8266-original.bin
```

Os próximos comandos substituem o firmware e o sistema de arquivos da placa. Use o nome do `.bin` baixado e a porta correta:

```bash
.venv/bin/python -m esptool --chip esp8266 --port /dev/ttyUSB0 erase-flash
.venv/bin/python -m esptool --chip esp8266 --port /dev/ttyUSB0 --baud 460800 write-flash --flash-size detect --flash-mode dout 0x0 ESP8266_GENERIC-VERSAO.bin
```

Se ficar em `Connecting...`, segure **FLASH**, aperte e solte **RST**, e solte FLASH quando iniciar a gravação. Se falhar em alta velocidade, use `--baud 115200`. Use MicroPython recente (1.24 ou posterior), na variante padrão com sistema de arquivos e `framebuf`. O endereço de gravação do ESP8266 é **0x0**. Procedimentos oficiais: [instalação do MicroPython no ESP8266](https://docs.micropython.org/en/latest/esp8266/tutorial/intro.html) e [esptool para ESP8266](https://docs.espressif.com/projects/esptool/en/latest/esp8266/esptool/basic-commands.html).

## 3. Gravar o aplicativo da tela

Feche Thonny, REPL, monitor serial e qualquer coletor que esteja usando a porta. Se o serviço já estiver instalado, pare-o antes de atualizar:

```bash
sudo systemctl stop tft-monitor
```

Liste as portas e grave:

```bash
.venv/bin/python scripts/flash.py --list
.venv/bin/python scripts/flash.py
```

Com mais de uma placa, escolha explicitamente:

```bash
.venv/bin/python scripts/flash.py --port /dev/ttyUSB0
```

O script verifica MicroPython e o modelo ESP8266, salva cópias dos arquivos existentes que serão substituídos em `backups/`, libera a memória do aplicativo anterior com um soft reset, copia `firmware/*.py`, verifica SHA-256 e reinicia a placa. Ele recusa ESP32 e Raspberry Pi Pico antes de escrever e **não instala o firmware base `.bin`**. O programa permanece no ESP8266 e inicia sempre que ligar. Depois de gravar, a tela aguarda dados USB.


## 4. Iniciar o monitoramento

```bash
.venv/bin/tft-monitor
```

O coletor procura dispositivos Espressif e adaptadores CP210x/CH340/CH9102 e confirma a identidade do aplicativo antes de enviar métricas. É possível fixar porta, intervalo, disco e interface:

```bash
.venv/bin/tft-monitor --port /dev/serial/by-id/SEU_ESP8266 --interval 1 --disk / --interface enp5s0
```

`--interface auto` usa interfaces físicas ativas e exclui loopback e interfaces virtuais reconhecidas. Escolha uma interface explicitamente para monitorar VPN, bridge ou outra rede virtual. `--disk` aceita um caminho de montagem, por exemplo `/home`; o percentual é de **espaço ocupado**, não atividade de leitura/escrita. Interrompa com `Ctrl+C`.

## 5. Iniciar automaticamente com o PC

Depois de testar a tela, encerre o coletor manual com `Ctrl+C`. Execute **no PC Linux que será monitorado**. No CachyOS ou Arch, o script abaixo instala as dependências e configura tudo:

```bash
sudo bash scripts/install-cachyos.sh
```

Em qualquer distribuição com **systemd ativo**, depois de instalar as dependências da etapa 1:

```bash
sudo bash scripts/install-service.sh
```

O instalador cria um usuário de serviço `tft-monitor`, instala o coletor em `/opt/tft-monitor/venv`, as permissões USB e um serviço systemd que inicia no boot, mesmo sem login. Não depende desta pasta continuar no mesmo lugar. Não grava nem apaga o ESP8266; a placa deve ter recebido o aplicativo nas etapas anteriores. A instalação precisa de internet para baixar dependências; o monitoramento normal funciona localmente por USB.

```bash
systemctl status tft-monitor
journalctl -u tft-monitor -f
sudo systemctl restart tft-monitor
```

Edite a configuração e reinicie para aplicá-la:

```bash
sudoedit /etc/tft-monitor.env
sudo systemctl restart tft-monitor
```

```ini
TFT_PORT=auto
TFT_INTERVAL=1
TFT_DISK=/
TFT_INTERFACE=auto
```

`TFT_PORT` aceita `/dev/serial/by-id/SEU_DISPOSITIVO` para escolher uma placa específica; liste os caminhos com `ls -l /dev/serial/by-id/`. `TFT_DISK` é um caminho existente e acessível ao usuário do serviço. `TFT_INTERFACE` aceita uma interface, por exemplo `enp5s0`; consulte `ip -brief link`.

| Ação | Comando |
| --- | --- |
| Parar temporariamente | `sudo systemctl stop tft-monitor` |
| Iniciar novamente | `sudo systemctl start tft-monitor` |
| Desativar início no boot e parar | `sudo systemctl disable --now tft-monitor` |
| Ativar novamente e iniciar | `sudo systemctl enable --now tft-monitor` |
| Ver mensagens do boot atual | `journalctl -u tft-monitor -b` |

Sem a placa, mensagens de nova tentativa nos logs são esperadas. A tela mostra dados desatualizados após cerca de cinco segundos sem amostras e volta ao painel quando recebe dados novamente.

Para atualizar o coletor, na pasta do projeto:

```bash
git pull --ff-only
sudo bash scripts/install-service.sh
```

Se baixou um ZIP, extraia a versão nova em outra pasta e execute o instalador nessa pasta em vez de usar `git pull`.

O instalador prepara um ambiente Python novo e preserva `/etc/tft-monitor.env`. Execute-o novamente depois de uma mudança de versão do Python que torne o ambiente anterior incompatível. Os ambientes anteriores ficam em `/opt/tft-monitor/venvs/` até a desinstalação. Se a atualização também alterar `firmware/`, pare o serviço, repita a etapa 3 e inicie o serviço novamente.

Para desinstalar o agente e remover o serviço, a aplicação e a regra USB:

```bash
sudo bash scripts/uninstall-service.sh
```

A configuração e o usuário/grupo de serviço são preservados para uma futura instalação. Use `sudo bash scripts/uninstall-service.sh --purge-config` para remover também `/etc/tft-monitor.env`. A desinstalação no Linux não altera o programa gravado na placa.

Em sistemas sem systemd, execute `.venv/bin/tft-monitor` manualmente ou configure o supervisor da distribuição para iniciar esse comando com caminho absoluto, usuário com acesso à serial e reinício em caso de falha. Este projeto não inclui unidades para OpenRC, runit ou outros sistemas de inicialização.

## Gravação pelo Windows / WSL

O WSL só consegue acessar a serial depois que o USB é encaminhado. Também é possível gravar diretamente pelo Windows, na pasta do projeto acessível pelo Explorer/PowerShell:

```powershell
py -3 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install pyserial mpremote "esptool>=5,<6"
.\.venv-win\Scripts\python.exe scripts\flash.py --list
.\.venv-win\Scripts\python.exe scripts\flash.py --port COM4
```

Substitua `COM4` pela porta real da placa. Para instalar MicroPython pelo Windows, use os comandos da etapa 2 com `.\.venv-win\Scripts\python.exe` e `--port COM4`. Não use `.venv` criada no Linux no Windows. COM1 identificada como `ACPI\PNP0501` é uma porta interna do PC, não identifica a placa USB.

Para encaminhar o USB ao WSL, instale [usbipd-win](https://learn.microsoft.com/en-us/windows/wsl/connect-usb), execute `usbipd list`, depois `usbipd bind --busid SEU_BUSID` em PowerShell administrador e `usbipd attach --wsl --busid SEU_BUSID`. A conexão pode precisar ser refeita após reset/reconexão da placa. Gravado o aplicativo, transfira o ESP8266 para o CachyOS e rode o coletor lá.

Para testar as **métricas do WSL** enquanto a USB continua no Windows, use os dois ambientes preparados acima. Execute na pasta do projeto, no terminal WSL:

```bash
.venv/bin/tft-monitor --dump | .venv-win/Scripts/python.exe -u "$(wslpath -w "$PWD/scripts/serial-stream.py")" --port COM4
```

O coletor Linux envia uma amostra por segundo; `serial-stream.py` acessa a COM pelo Python do Windows, confirma a resposta do ESP8266 e tenta reconectar se a USB cair. A ponte mantém apenas a amostra mais recente e não repete dados quando o coletor para. Encerre com `Ctrl+C` antes de gravar novamente a placa. No CachyOS nativo, use diretamente `.venv/bin/tft-monitor`, sem essa ponte.

## Ajustar a tela

Há variantes do ST7735 com ordem de cor e deslocamento diferentes. Edite [firmware/config.py](firmware/config.py) e grave novamente:

| Sintoma | Ajuste |
| --- | --- |
| Vermelho e azul trocados | Inverta `BGR` |
| Imagem deslocada/cortada | Ajuste `X_OFFSET` e `Y_OFFSET` conforme o módulo |
| Cores em negativo | Inverta `INVERT` |
| Tela de cabeça para baixo | Troque `ROTATION` entre `1` e `3` |
| Ruído ou atualização instável | Reduza `SPI_BAUDRATE` para `5_000_000` |

O padrão é paisagem **`ROTATION = 3`**, girado 180° em relação a `ROTATION = 1`, SPI a 10 MHz e deslocamentos zero. A calibração física depende da variante do seu módulo. A pinagem da NodeMCU está em `firmware/config.py` e corresponde à tabela acima. O painel foi desenhado para paisagem em 160 × 128; as orientações de retrato do driver não adaptam automaticamente o layout.

## Métricas opcionais e diagnóstico

Para o erro `Cannot configure port` no Windows com CH340, consulte o [guia de diagnóstico USB no Windows](docs/USB_WINDOWS.md). O estado dos testes está em [VALIDACAO.md](docs/VALIDACAO.md).

- Temperatura aparece como indisponível quando o kernel não expõe um sensor de CPU reconhecido. No CachyOS, `lm_sensors` e o comando `sensors` ajudam a conferir os sensores.
- NVIDIA usa `nvidia-smi`, se disponível no driver. AMD usa `gpu_busy_percent` e sensores de `/sys/class/drm`. GPUs sem esses recursos ficam sem leitura. O painel mostra uma GPU.
- A tela informa perda de dados depois de aproximadamente cinco segundos sem amostras. Retoma sozinha quando o coletor volta. Se aumentar `--interval` para cinco segundos ou mais, aumente também `STALE_MS` em `firmware/config.py` e grave novamente.
- Tela branca: confira VDD/BLK, GND, DC/RST/CS e se o aplicativo foi copiado. Para ver uma exceção do firmware, pare o coletor e abra `.venv/bin/mpremote connect /dev/ttyUSB0 repl`.
- Porta ocupada: encerre Thonny/mpremote/coletor concorrente. O serviço também precisa ser parado durante gravação.
- Nenhuma porta USB: confira cabo de dados, driver CP210x/CH340 no Windows e encaminhamento do USB se estiver no WSL.
- `TFT MONITOR / aguardando USB / sem dados`: a placa iniciou; falta um coletor conectado. Confira `systemctl status tft-monitor` e os logs, ou execute `.venv/bin/tft-monitor --verbose` depois de parar o serviço.
- `Permission denied` no Linux: aplique as regras USB da etapa 1 e reconecte a placa. Para acesso remoto sem sessão gráfica, adicione seu usuário ao grupo `tft-monitor` com `sudo usermod -aG tft-monitor "$USER"` e faça novo login.
- Selecione somente um coletor por porta; o serviço e o comando manual não devem usar a mesma placa ao mesmo tempo.

## Desenvolvimento

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q host firmware scripts
```

Os testes usam dublês de hardware e cobrem coleta, protocolo, framebuffer/driver e gravação. Não substituem a conferência física de cor, orientação e estabilidade SPI.

```text
firmware/           MicroPython, driver ST7735 e painel
host/tft_monitor/   coletor Linux e transporte USB
scripts/            preparação, gravação com backup, instalação do serviço
systemd/            serviço, configuração e regra USB
tests/              testes automatizados sem placa
```

O transporte usa JSON por linha, versão `1`. `hello` recebe `ready` com `device: tft-monitor`; apenas depois são enviados pacotes `stats`. As taxas `rx`/`tx` são bytes/s; percentuais vão de 0 a 100; temperaturas são °C ou `null`. O firmware aceita no máximo 1.024 bytes por linha e descarta entradas inválidas.

Referências: [MicroPython ESP8266](https://docs.micropython.org/en/latest/esp8266/quickref.html), [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html), [permissões udev no Arch](https://wiki.archlinux.org/title/Udev#Allowing_regular_users_to_use_devices).
