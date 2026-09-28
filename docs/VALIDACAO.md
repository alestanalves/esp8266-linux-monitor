# Validação do projeto

Registro de 28/09/2026 para **ESP8266 NodeMCU V3 + TFT ST7735 de 1,8 polegada**.

## Testes automatizados

A revisão de publicação passou em **72 testes e 52 subtestes**, executados com:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q host firmware scripts
```

Os testes cobrem coleta de métricas, protocolo JSON, identificação serial, inicialização sem USB e conexão posterior, reconexão, entradas inválidas, driver e framebuffer, instalação do firmware com backup e encaminhamento WSL/Windows. Um teste usa pyserial e um pseudo-terminal Linux para exercitar a comunicação real entre o coletor e o parser do firmware, sem placa.

Os testes do instalador usam diretórios temporários e comandos de sistema simulados: verificam instalação inicial, atualização de ambientes antigos, preservação da configuração, falhas antes da troca do serviço e desinstalação. Não alteram serviços nem contas do computador que executa os testes.

Também foram verificados a sintaxe dos scripts Bash, a construção do pacote Python e a sintaxe da unidade systemd. Para verificar a unidade sem instalar `/opt/tft-monitor`, o teste usa uma cópia temporária com `ExecStart=/usr/bin/true`; isso não equivale a iniciar o serviço em uma distribuição real.

O [workflow de testes](../.github/workflows/tests.yml) executa a suíte no GitHub Actions com Python 3.10, 3.13 e 3.14. O resultado de cada revisão pode ser consultado na aba Actions do repositório.

## Testes físicos realizados

- ESP8266EX com **4 MiB de flash**, adaptador USB CH340 e pinagem descrita no [README](../README.md).
- Backup integral da flash antes de instalar **MicroPython 1.29.0 / ESP8266_GENERIC** em `0x0`, com modo DOUT e hash da gravação conferido pelo esptool.
- Cinco arquivos do aplicativo enviados e verificados por SHA-256 na placa, seguidos de reinicialização.
- Handshake USB, envio de métricas reais e novas respostas após as amostras e após uma pausa de 5,5 segundos.
- Envio contínuo de mais de 120 amostras, a uma por segundo, com respostas periódicas do aplicativo.
- Dez atualizações do painel, incluindo dados desatualizados: memória livre após coleta de lixo de **13.392 bytes antes** e **13.360 bytes depois**. Framebuffer de 10.240 bytes, linha de conversão de 320 bytes e paleta de 32 bytes.
- Tela física exibindo a mensagem de espera. A rotação foi posteriormente alterada para `ROTATION = 3`, girando a imagem 180° e mantendo o painel em 160 × 128; a atualização foi gravada e verificada.

Os testes de comunicação usaram métricas de Linux no WSL e a porta USB acessada pelo Windows. Backups, instaladores de terceiros, imagens `.bin` baixadas e logs locais não fazem parte do código-fonte publicado.

## Limites desta validação

Não foi realizado um ciclo de desligar e ligar um computador CachyOS com este serviço instalado. A configuração do boot foi verificada por testes do instalador e da unidade systemd; o primeiro boot no PC de destino deve ser conferido com `systemctl status tft-monitor` e `journalctl -u tft-monitor -b`.

As instruções para outras distribuições não significam que todas foram testadas fisicamente. Sensores de CPU/GPU dependem do hardware e do driver. Cores, offsets e orientação devem ser conferidos no módulo TFT usado; os testes automatizados não substituem essa observação.
