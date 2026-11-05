## ADDED Requirements

### Requirement: Shared composable TUI library / Biblioteca TUI compartilhada e componível

The two plugins MUST bundle the same pinned, canonical `herdr_shared_ui` package. The package MUST use Python `curses` and standard-library code only, organize APIs around reusable responsibilities, and remain usable without network access, Textual, or a sibling checkout. / Os dois plugins DEVEM embutir o mesmo pacote `herdr_shared_ui` canônico e com versão fixada. O pacote DEVE usar Python `curses` e apenas a biblioteca padrão, organizar APIs por responsabilidades reutilizáveis e funcionar sem rede, Textual ou checkout irmão.

#### Scenario: Independent plugin startup / Inicialização independente do plugin

- **WHEN** either plugin starts from its installed bundle / **QUANDO** qualquer plugin inicia a partir do pacote instalado
- **THEN** it imports the shared modules locally without network access or another plugin checkout / **ENTÃO** importa os módulos compartilhados localmente sem rede nem checkout do outro plugin

### Requirement: Shared Markdown and common layout / Markdown compartilhado e layout comum

Markdown parsing and formatting shared by the two viewers MUST have one canonical implementation in the shared package. Common row wrapping and layout MAY be shared where behavior is identical. Plugin-specific zoom, navigation, selection, cursor, selectable-block policy, and comments MUST remain under plugin control. / A análise e formatação Markdown compartilhadas pelos dois viewers DEVEM ter uma implementação canônica no pacote comum. A quebra e o layout de linhas PODEM ser compartilhados onde o comportamento for idêntico. Zoom, navegação, seleção, cursor, política dos blocos selecionáveis e comentários DEVEM permanecer sob controle de cada plugin.

#### Scenario: Same Markdown rendering / Mesma renderização Markdown

- **WHEN** both plugins render the same supported Markdown input / **QUANDO** os dois plugins renderizam a mesma entrada Markdown suportada
- **THEN** they use the same shared formatting rules and bundled implementation / **ENTÃO** usam as mesmas regras de formatação e implementação embutida

#### Scenario: Plugin-specific interaction / Interação específica do plugin

- **WHEN** a plugin applies its viewer navigation or selection policy / **QUANDO** um plugin aplica sua política de navegação ou seleção
- **THEN** the shared Markdown library does not impose the other plugin's interaction behavior / **ENTÃO** a biblioteca Markdown compartilhada não impõe o comportamento de interação do outro plugin

### Requirement: Bundle synchronization / Sincronização dos pacotes

The canonical shared package MUST provide a repeatable way to sync both plugin bundles and detect stale or divergent copies. / O pacote compartilhado canônico DEVE oferecer uma forma repetível de sincronizar as duas cópias e detectar cópias divergentes ou desatualizadas.

#### Scenario: Bundle verification / Verificação dos pacotes

- **WHEN** the shared package conformance check runs / **QUANDO** a verificação de conformidade do pacote compartilhado é executada
- **THEN** it reports whether each plugin bundle matches the selected canonical version and digest / **ENTÃO** informa se o pacote de cada plugin corresponde à versão e ao digest canônicos selecionados
