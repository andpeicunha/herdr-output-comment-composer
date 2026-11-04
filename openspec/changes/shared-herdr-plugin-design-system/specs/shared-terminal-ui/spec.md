## ADDED Requirements

### Requirement: Bundled shared terminal UI / Interface de terminal compartilhada embutida

Comments MUST bundle the pinned shared UI and use it without fetching components at runtime. / Comments DEVE embutir a interface compartilhada com versão fixa e usá-la sem buscar componentes durante a execução.

#### Scenario: Independent startup / Inicialização independente

- **WHEN** the plugin starts from its checkout / **QUANDO** o plugin inicia do seu checkout
- **THEN** it imports the bundled UI without another plugin or network access / **ENTÃO** importa a interface embutida sem outro plugin ou acesso à rede

### Requirement: Full-row selection / Seleção em toda a linha

Selected content MUST fill the available row, including wrapped and code rows, and distinguish the active cursor in a range. / O conteúdo selecionado DEVE preencher a linha disponível, inclusive linhas quebradas e de código, e distinguir o cursor ativo em uma seleção.

#### Scenario: Range selection / Seleção de intervalo

- **WHEN** a selection spans wrapped text and code / **QUANDO** uma seleção abrange texto quebrado e código
- **THEN** every selected row is filled and the active cursor remains visible / **ENTÃO** cada linha selecionada é preenchida e o cursor ativo continua visível
