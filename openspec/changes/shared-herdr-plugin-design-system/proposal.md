## Why / Por quê

Comments and Spec Review need consistent terminal visuals without a runtime dependency between plugins. / Comments e Spec Review precisam de visuais de terminal consistentes sem dependência entre plugins em execução.

## What changes / O que muda

Bundle the pinned shared curses UI and use its palette and drawing primitives in Comments, preserving its navigation and selection behavior. / Embutir a interface curses compartilhada com versão fixa e usar sua paleta e componentes de desenho no Comments, preservando navegação e seleção.

## Impact / Impacto

The complete plugin checkout remains self-contained; maintainers update the bundled copy explicitly. / O checkout completo continua independente; mantenedores atualizam a cópia embutida explicitamente.
