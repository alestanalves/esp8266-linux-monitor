# USB CH340 no Windows e uso pelo WSL

A NodeMCU V3 costuma usar um adaptador CH340. No Gerenciador de Dispositivos, procure **Portas (COM e LPT) → USB-SERIAL CH340 (COMn)**. Use essa porta nos comandos; `COM4` nos exemplos é apenas uma referência.

## A porta aparece, mas não pode ser configurada

Erros como `Cannot configure port`, `can't set com-state` ou erro Windows 31 podem ocorrer em determinados lotes CH340 com drivers recentes. Antes de alterar drivers, feche Thonny, mpremote e outros monitores seriais e confira o cabo USB de dados.

O [procedimento oficial do suporte Arduino](https://support.arduino.cc/hc/en-us/articles/13148652511260-avrdude-ser-open-can-t-set-com-state-for-COMn) explica o problema e fornece o download e as instruções para a versão **3.7.2022.1**. Siga esse procedimento quando o sintoma corresponder. A instalação do driver requer autorização de administrador do Windows.

1. Anote a versão atual na aba Driver do dispositivo e mantenha uma cópia do instalador ou backup do driver anterior.
2. Use o download indicado pelo suporte Arduino e confira a assinatura digital do instalador. Não há instaladores de drivers neste repositório.
3. Instale o pacote e siga as instruções do artigo para selecionar a versão, se necessário.
4. Reconecte a placa, confira a versão ativa e o número da porta.
5. Verifique o chip usando o Python do Windows preparado no [README](../README.md):

```powershell
.\.venv-win\Scripts\python.exe -m esptool --chip esp8266 --port COM4 flash-id
```

Na placa utilizada para validar este projeto, substituir 3.9.2024.9 por 3.7.2022.1 resolveu a configuração serial e permitiu ler e gravar o ESP8266. Essa observação não exige trocar um driver que já funciona em outro computador.

Se a porta abre normalmente, mas a gravação permanece em `Connecting...`, consulte o procedimento com os botões FLASH/RST no README; é uma etapa diferente da configuração do driver.

## Acesso pelo WSL

Uma porta COM do Windows não aparece automaticamente como `/dev/ttyUSB0` no WSL. Há duas opções descritas no README:

- Encaminhar a USB ao Linux usando [usbipd-win, conforme a documentação Microsoft](https://learn.microsoft.com/en-us/windows/wsl/connect-usb).
- Manter a USB no Windows e encaminhar o JSON do coletor Linux para `scripts/serial-stream.py`, executado pelo Python do Windows.

No CachyOS instalado diretamente no computador, execute o coletor Linux pela porta serial, sem a ponte WSL. Somente um coletor ou ferramenta de gravação deve abrir a placa por vez.
