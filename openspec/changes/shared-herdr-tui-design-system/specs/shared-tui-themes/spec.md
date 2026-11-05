## ADDED Requirements

### Requirement: Configurable viewer themes / Temas configuráveis do viewer

Each plugin MUST let its developer choose a shared named theme in that plugin's configuration. The shared theme set MUST include a terminal-default option and named curated themes. Unsupported terminals or invalid settings MUST fall back safely. The viewer MUST NOT depend on or inherit Herdr's active theme. / Cada plugin DEVE permitir que a pessoa desenvolvedora escolha um tema compartilhado nomeado na configuração daquele plugin. O conjunto compartilhado DEVE incluir uma opção que respeita as cores do terminal e temas nomeados selecionados. Terminais sem suporte ou configurações inválidas DEVEM usar uma alternativa segura. O viewer NÃO DEVE depender nem herdar o tema ativo do Herdr.

#### Scenario: Configured theme on startup / Tema configurado na inicialização

- **WHEN** the viewer starts with a supported theme configured / **QUANDO** o viewer inicia com um tema suportado configurado
- **THEN** all shared semantic tokens use that theme / **ENTÃO** todos os tokens semânticos compartilhados usam esse tema

#### Scenario: Terminal fallback / Fallback do terminal

- **WHEN** no theme is configured, a theme name is invalid, or the terminal lacks required color support / **QUANDO** nenhum tema está configurado, o nome do tema é inválido ou o terminal não oferece o suporte de cor necessário
- **THEN** the viewer uses a readable terminal-default or reduced-color palette / **ENTÃO** o viewer usa uma paleta legível que respeita as cores do terminal ou reduzida

### Requirement: Live theme switching / Troca de tema ao vivo

The viewer MUST let users cycle through supported themes while the pane is open, redraw immediately, and persist the selected theme in that plugin's configuration. The `?` help MUST list the `t` shortcut. / O viewer DEVE permitir alternar entre os temas suportados enquanto a pane está aberta, redesenhar imediatamente e persistir o tema selecionado na configuração daquele plugin. A ajuda `?` DEVE listar o atalho `t`.

#### Scenario: Cycle theme while viewing / Alternar tema durante a leitura

- **WHEN** the user presses `t` in the open viewer / **QUANDO** a pessoa pressiona `t` no viewer aberto
- **THEN** the next theme is applied immediately and the updated selection is retained for the next launch / **ENTÃO** o próximo tema é aplicado imediatamente e a seleção atualizada permanece na próxima inicialização

#### Scenario: Discover theme shortcut / Descobrir atalho de tema

- **WHEN** the user opens the viewer help with `?` / **QUANDO** a pessoa abre a ajuda do viewer com `?`
- **THEN** the help identifies `t` as the live theme-cycle shortcut / **ENTÃO** a ajuda identifica `t` como o atalho para alternar o tema ao vivo
