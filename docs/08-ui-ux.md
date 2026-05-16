# UI/UX — Dashboard, Spreadsheet & Brand Sites

> **Module:** `src/code_agent/ui/` — HTML/CSS/JS served via FastAPI

Orchestra provides a complete web-based user interface with three brand sites, an interactive dashboard, and an Excel-like spreadsheet — all in a single self-contained Python module.

---

## Pages

| Route | Page | Type | Size |
|-------|------|------|------|
| `/` | Main Orchestra UI | Agent interface | ~50KB |
| `/create` | Orchestra Create | Brand site | 24KB |
| `/finance` | Orchestra Finance | Brand site | 15KB |
| `/finance/app` | Finance Dashboard + Spreadsheet | App | 32KB |
| `/logistics` | Orchestra Logistics | Brand site | 15KB |
| `/logistics/app` | Logistics Dashboard | App | 25KB |

All pages are fully self-contained — HTML, CSS, and JS inline. No build step required.

---

## Main UI — `/`

The primary Orchestra agent interface featuring:
- JARVIS mode toggle with gradient accent
- Web Speech API mic button for voice input
- Image upload/paste support
- TTS (text-to-speech) for agent responses
- Responsive CSS (5 breakpoints down to 375px)
- Glassmorphism header
- Custom scrollbars
- Toast notification system
- PWA manifest + service worker for offline support
- Spaces/Artifacts sidebar — group chats by project, manage generated outputs

---

## Brand Sites

All three brand sites share a consistent design system:

**Design tokens:**
- Dark theme with `#0a0a0f` / `#06080e` / `#060a0f` backgrounds
- Gradient accents: Create (purple→teal), Finance (blue→green), Logistics (blue→green)
- Floating CSS background orbs with keyframe animations
- `Inter` + `JetBrains Mono` typography
- Glassmorphism nav with backdrop-filter
- Custom scrollbars
- 3 responsive breakpoints (768px, 480px)

### Orchestra Create — `/create`
- Hero: animated badge, gradient text, CTA buttons, stats
- Features: 6 cards (Concept to Code, Adaptive Workflows, Design Intelligence, etc.)
- Workflow: 4-step (Describe → Generate → Refine → Deploy)
- Templates: 6 project types with tag chips (Web, Rust, TS, Mojo, Design System, API)
- Testimonials: 3 cards with star ratings
- Pricing: 3 tiers (Free / $19 Pro / $99 Enterprise)
- Modal form: project type dropdown + email + description

### Orchestra Finance — `/finance`
- Hero: gradient text, stats badges
- Features: 6 cards (Dashboards, Spreadsheet, KPIs, Export, Live Updates, Local-First)
- Pricing: 3 tiers with "Popular" badge

### Orchestra Logistics — `/logistics`
- Hero: enterprise messaging, stats
- Features: 6 cards (Fleet, Route Optimization, Supply Chain, AI, Dashboards, Enterprise)
- Pricing: 2 tiers (Free / Custom Enterprise)

---

## Finance App — `/finance/app`

### Dashboard Tab
| Feature | Implementation |
|---------|---------------|
| KPI cards | 4 cards: Revenue, Expenses, Net Profit, Cash Flow |
| Bar chart | Canvas API — monthly revenue |
| Pie chart | Canvas API — expense breakdown |
| Line chart | Canvas API — profit trend |
| Transactions table | 12 sample entries with income/expense/investment tagging |
| Add Transaction | Generates realistic random entries |
| Export CSV | UTF-8 BOM encoded |

### Spreadsheet Tab
| Feature | Implementation |
|---------|---------------|
| Grid | 12 columns × 7 rows, editable cells |
| Cell reference | Click any cell → shows `A1`, `B2`, etc. |
| Formula bar | Type formulas or values, Enter to confirm |
| Standard formulas | `=SUM()`, `=AVG()`, `=MAX()`, `=MIN()`, `=COUNT()` |
| AI-native formulas | `=AI_PROJECT()`, `=EXPLAIN_VARIANCE()`, `=FORECAST()`, `=RISK_ANALYSIS()` |
| Add Row/Col | Buttons to expand grid |
| Tab navigation | Tab key moves to next cell |
| Auto-refresh | Spreadsheet changes update dashboard charts |

### Insights Tab
| Feature | Implementation |
|---------|---------------|
| CFO Copilot | Free-text question → POST to `/api/finance/brain/query` |
| AI Insights | Auto-generated: profit margin, revenue growth, operating loss |
| What-If Scenarios | Bullish (+25%), Moderate (+10%), Cost Optimized (-15%), Downturn (-20%) |
| Forecast card | Next 3 months revenue projection |
| Risk card | Value at Risk (95% confidence) |
| AI Formula reference | Copy-paste examples for spreadsheet |

---

## Logistics App — `/logistics/app`

### Fleet Tab
- 5 KPI cards: Fleet size, Available, In Transit, Maintenance, Utilization
- Vehicles table: name, plate, type, status (color-coded), region
- Drivers table: name, status, hours this week, remaining hours

### Resources Tab
- Warehouse utilization bars (green/yellow/red)
- Inventory table: SKU, name, quantity, total value, reorder status
- Total inventory value display

### Supply Chain Tab
- Shipment KPIs: total shipments, total profit, on-time rate, delivery success rate
- Shipments table: tracking code, origin→destination, status (color-coded), profit

### AI Tab
| Feature | Implementation |
|---------|---------------|
| Logistics Copilot | Free-text Q → POST to `/api/logistics/brain/query` |
| Anomaly list | Color-coded by severity (critical/warning) |
| Demand forecast chart | Canvas line chart with historical + projected (dashed line) |
| Fleet health score | Large letter grade (A/B/C/D) with sub-score and reasons |

---

## Design System

### CSS Variables
```css
:root {
  --bg: #0a0a0f;
  --bg2: #12121a;
  --surface: #1e1e2e;
  --border: #2a2a3e;
  --text: #e4e4f0;
  --text2: #9494b0;
  --accent: #7c6ff0;
  --accent2: #5ee0c0;
  --radius: 16px;
  --font: 'Inter', system-ui, sans-serif;
  --mono: 'JetBrains Mono', monospace;
}
```

### Responsive Breakpoints
| Breakpoint | Behavior |
|------------|----------|
| >768px | Full layout, horizontal nav |
| 768px | Stack grids, hamburger nav |
| 480px | Single column, stacked CTA buttons |

### Interactive Elements
| Element | Behavior |
|---------|----------|
| Feature cards | Hover: translateY(-4px), border accent |
| Nav CTA | Hover: glow shadow |
| Floating orbs | Infinite float animation (18-25s) |
| Status badges | Color-coded backgrounds |
| Progress bars | Gradient fills with threshold colors |
