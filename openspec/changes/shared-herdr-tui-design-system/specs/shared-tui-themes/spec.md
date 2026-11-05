## ADDED Requirements

### Requirement: Configurable viewer themes / Temas configuráveis do viewer

Each plugin MUST let its developer choose a shared named theme in that plugin's configuration. The shared theme set MUST include `herdr-dark` as the visible default and `terminal` as an explicit option for inheriting terminal colors. Missing or invalid settings MUST use `herdr-dark`. Unsupported terminals MUST use a readable reduced-color palette. The viewer MUST NOT depend on or inherit Herdr's active theme. / Cada plugin DEVE permitir que a pessoa desenvolvedora escolha um tema compartilhado nomeado na configuração daquele plugin. O conjunto compartilhado DEVE usar `herdr-dark` como padrão visual e oferecer `terminal` como opção explícita para respeitar as cores do terminal. Configurações ausentes ou inválidas DEVEM usar `herdr-dark`. Terminais sem suporte DEVEM usar uma paleta reduzida e legível. O viewer NÃO DEVE depender nem herdar o tema ativo do Herdr.

#### Scenario: Configured theme on startup / Tema configurado na inicialização

- **WHEN** the viewer starts with a supported theme configured / **QUANDO** o viewer inicia com um tema suportado configurado
- **THEN** all shared semantic tokens use that theme / **ENTÃO** todos os tokens semânticos compartilhados usam esse tema

#### Scenario: Styled default / Padrão visual

- **WHEN** no theme is configured or the configured theme name is invalid / **QUANDO** nenhum tema está configurado ou o nome informado é inválido
- **THEN** the viewer starts with the `herdr-dark` blue and cyan palette / **ENTÃO** o viewer inicia com a paleta azul e ciano de `herdr-dark`

#### Scenario: Explicit terminal colors / Cores explícitas do terminal

- **WHEN** the user configures `terminal` / **QUANDO** a pessoa configura `terminal`
- **THEN** the viewer uses the terminal's own colors / **ENTÃO** o viewer respeita as cores do terminal

### Requirement: Live theme switching / Troca de tema ao vivo

The viewer MUST let users cycle through supported themes while the pane is open, redraw immediately, and persist the selected theme in that plugin's configuration. The `?` help MUST list the `t` shortcut. / O viewer DEVE permitir alternar entre os temas suportados enquanto a pane está aberta, redesenhar imediatamente e persistir o tema selecionado na configuração daquele plugin. A ajuda `?` DEVE listar o atalho `t`.

#### Scenario: Cycle theme while viewing / Alternar tema durante a leitura

- **WHEN** the user presses `t` in the open viewer / **QUANDO** a pessoa pressiona `t` no viewer aberto
- **THEN** the next theme is applied immediately and the updated selection is retained for the next launch / **ENTÃO** o próximo tema é aplicado imediatamente e a seleção atualizada permanece na próxima inicialização

#### Scenario: Discover theme shortcut / Descobrir atalho de tema

- **WHEN** the user opens the viewer help with `?` / **QUANDO** a pessoa abre a ajuda do viewer com `?`
- **THEN** the help identifies `t` as the live theme-cycle shortcut / **ENTÃO** a ajuda identifica `t` como o atalho para alternar o tema ao vivo
