// Generates the official OpenUI system prompt from the installed chat component library.
// Also emits an ultra-compact variant (~5.5 KB, ~1,400 tokens) so multiple turns per minute
// fit comfortably under Groq's 8,000 TPM free-tier limit, using 100% authentic OpenUI signatures.
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { openuiChatLibrary, openuiChatPromptOptions } from '@openuidev/react-ui';

const here = dirname(fileURLToPath(import.meta.url));
const outFull = resolve(here, '../../harness/openui_system_prompt.txt');
const outCompact = resolve(here, '../../harness/openui_system_prompt_compact.txt');

const fullPrompt = openuiChatLibrary.prompt(openuiChatPromptOptions);
mkdirSync(dirname(outFull), { recursive: true });
writeFileSync(outFull, fullPrompt, 'utf-8');

const KEEP_COMPONENTS = new Set([
  'Card',
  'CardHeader',
  'TextContent',
  'InlineHeader',
  'Callout',
  'TagBlock',
  'Tag',
  'EntityList',
  'Table',
  'Col',
  'BarChart',
  'LineChart',
  'PieChart',
  'Series',
  'ContextCardBlock',
  'ContextCardItem',
  'OverviewCardBlock',
  'OverviewCardItem',
  'Text',
  'BoldText',
  'IconText',
  'MetricIndicatorInline',
  'ListBlock',
  'ListItem',
  'FollowUpBlock',
  'FollowUpItem',
  'Buttons',
  'Button',
  'Icon',
  'Tabs',
  'TabItem',
]);

const lines = fullPrompt.split('\n');
const compact = [];
let skipSection = false;
let inSig = false;

for (const line of lines) {
  if (line.startsWith('## Action') || line.startsWith('## Hoisting') || line.startsWith('## Examples') || line.startsWith('## Important Rules') || line.startsWith('## Final Verification')) {
    inSig = false;
    skipSection = true;
    continue;
  }
  if (line.startsWith('## Component Signatures')) {
    skipSection = false;
    inSig = true;
    compact.push(line);
    continue;
  }
  if (line.startsWith('## ')) {
    skipSection = false;
    inSig = false;
  }
  if (skipSection) continue;

  if (inSig) {
    if (line.startsWith('### ')) continue;
    const compMatch = line.match(/^([A-Z][A-Za-z0-9]*)\(/);
    if (compMatch && KEEP_COMPONENTS.has(compMatch[1])) {
      // Keep the exact positional signature, drop long prose after ' — '
      const dashIdx = line.indexOf(' — ');
      compact.push(dashIdx > 0 ? line.slice(0, dashIdx) : line);
    }
    continue;
  }

  compact.push(line);
}

compact.push('');
compact.push('## Actions & Rules');
compact.push('- Actions: `@ToAssistant("message")` on Button/ListItem/CardBlock, or `@OpenUrl("https://...")`.');
compact.push('- Every response is a single `root = Card([...])` defined on the FIRST line; every defined variable must be referenced.');
compact.push('- Never invent image URLs; without a real URL use `ContextCardBlock` with `"gray"` background and `Tag`/`Icon`.');
compact.push('- Table is column-oriented (`Col(label, dataArray)`). Quantitative asks get a Chart + OverviewCardBlock.');
compact.push('');
compact.push('## Example');
compact.push('root = Card([hdr, intro, cards, btnRow, fups])');
compact.push('hdr = CardHeader("Modern Hotels in Paris", "Curated architectural stays")');
compact.push('intro = TextContent("Top contemporary hotels selected for your trip:")');
compact.push('cards = ContextCardBlock([c1, c2, c3], "grid", true, @ToAssistant("Tell me more about this hotel"))');
compact.push('c1 = ContextCardItem("le-six", t1, "6th Arr. · Minimalist rooms, spa & rooftop terrace · €€€", "gray")');
compact.push('t1 = Tag("Boutique", i1, "sm", "info")');
compact.push('i1 = Icon("sparkles", "shapes")');
compact.push('c2 = ContextCardItem("hoxton", t2, "2nd Arr. · Industrial-chic courtyard & lively bar · €€", "gray")');
compact.push('t2 = Tag("Trendy", i2, "sm", "success")');
compact.push('i2 = Icon("coffee", "food")');
compact.push('c3 = ContextCardItem("atelier", t3, "1st Arr. · Near Louvre, bright modern suites · €€€", "gray")');
compact.push('t3 = Tag("Central", i3, "sm", "neutral")');
compact.push('i3 = Icon("map-pin", "travel")');
compact.push('btnRow = Buttons([b1], "row")');
compact.push('b1 = Button("Compare Neighborhoods", @ToAssistant("Compare these Paris neighborhoods"), "secondary")');
compact.push('fups = FollowUpBlock([f1, f2])');
compact.push('f1 = FollowUpItem("Filter under €250/night")');
compact.push('f2 = FollowUpItem("Show boutique hotels with a spa")');

const compactPrompt = compact.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
writeFileSync(outCompact, compactPrompt, 'utf-8');
console.log(`Wrote full (${fullPrompt.length} chars) and compact (${compactPrompt.length} chars)`);
