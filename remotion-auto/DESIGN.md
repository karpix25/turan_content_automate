# Design System: Turan AutoMontage

**Status:** AI-Native Design Specification (SDR-1)

## 1. Visual Theme & Atmosphere
The design follows a **"Modern Video Insight"** philosophy. It is optimized for dynamic video overlays where content must be punchy, legible, and "high-end" in a few seconds of screen time.
- **Vibe:** Technical, Professional, Energetic.
- **Visual Strategy:** Deep matte backgrounds combined with glassmorphism and vibrant, glowing accents to draw attention to key data.

## 2. Color Palette & Roles (Systemic)

| Name | Role | Example Hex (Business) |
| :--- | :--- | :--- |
| **Clear Insight White** | Main text and primary readability. | `#F7F4FF` |
| **Muted Lavender** | Secondary info, supporting text, and breadcrumbs. | `#D8D0EA` |
| **Deep Cerulean (Accent)** | Focus words, icons, and primary state markers. | `#7BD2FF` |
| **Sunset Gold (CTA)** | Calls to action, progress indicators, and highlight points. | `#FFC58B` |
| **Obsidian Glass** | Semi-transparent backgrounds for panels. | `rgba(22, 15, 34, 0.62)` |
| **Pulse Glow** | Soft shadows and outer glows for "insight" components. | `rgba(123, 210, 255, 0.34)` |

## 3. Typography Rules
- **Primary Face:** `"Avenir Next"`, `"Montserrat"`. Used for readability and data.
    - **Body:** Weight 500-600.
    - **Headlines:** Weight 760 (Heavy). Letter spacing `-0.35` to create a dense, "news-ticker" feel.
- **Accent Face:** `"Oswald"`, `"Bebas Neue"`. Used for labels and uppercase categories.
    - **Style:** All-caps, slightly condensed.

## 4. Component Stylings

### Panels (Content Containers)
- **Shape:** Generously rounded corners (**32px**).
- **Surface:** `linear-gradient(165deg, Strong 0%, Standard 100%)`.
- **Depth:** 20px-50px blur shadows using the `insightGlow` color to create a "floating" effect.
- **Border:** 1px solid stroke with 40-50% opacity of the `Accent` color to define edges on dark backgrounds.

### Data Bars & Chips
- **Shape:** Full pill-shaped (**999px**).
- **Background:** `rgba(255, 255, 255, 0.14)` for empty states.
- **Progress:** Gradient from `Accent` to `CTA` to show movement/growth.

### Word Cues (Subtitles)
- **Styling:** Floating chips with `1px solid ${theme.accent}66`.
- **Text:** Semibold (620), 24px-28px.

## 5. Layout Principles
- **Density:** High. Content is packed into side-panels to keep the center-lane clear for the main video asset.
- **Margins:** Standard outer gutter of **50px** on all sides.
- **Vertical Spacing:** 16px-20px between blocks to maintain a clean "grid-less" hierarchy.
