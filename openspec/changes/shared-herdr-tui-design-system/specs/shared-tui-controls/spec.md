## ADDED Requirements

### Requirement: Native reusable controls / Controles nativos reutilizáveis

The shared TUI package MUST provide lightweight button and modal controls built with Python `curses` and the standard library. Buttons MUST be usable by keyboard without mouse support and expose focused/selected state. Mouse activation MAY be supported when available. Plugins MUST provide the action labels and handlers so domain behavior remains local. / O pacote TUI compartilhado DEVE oferecer controles leves de botão e modal feitos com Python `curses` e a biblioteca padrão. Os botões DEVEM funcionar pelo teclado sem suporte a mouse e expor o estado de foco/seleção. A ativação pelo mouse PODE ser oferecida quando disponível. Os plugins DEVEM fornecer rótulos e funções de ação para manter o comportamento de domínio local.

#### Scenario: Keyboard-operated confirmation / Confirmação operada pelo teclado

- **WHEN** a plugin opens a confirmation modal with multiple actions / **QUANDO** um plugin abre um modal de confirmação com várias ações
- **THEN** the user can move focus between buttons and activate the focused action with the keyboard / **ENTÃO** a pessoa pode mover o foco entre os botões e ativar a ação focada pelo teclado

#### Scenario: Plugin-owned action / Ação definida pelo plugin

- **WHEN** the shared modal dispatches a selected action / **QUANDO** o modal compartilhado encaminha a ação selecionada
- **THEN** it calls the handler supplied by the plugin and does not impose send, discard, or cancel policy / **ENTÃO** chama a função fornecida pelo plugin e não impõe a política de enviar, descartar ou cancelar
