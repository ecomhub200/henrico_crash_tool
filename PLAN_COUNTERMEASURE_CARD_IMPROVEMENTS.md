# Plan: Countermeasure Card Improvements

## Problem Analysis

The AI-generated countermeasure cards (first screenshot) have significant data display issues compared to the algorithmic "Find Countermeasure" cards (second screenshot).

### Current Issues in AI Cards

| Issue | Current Display | Expected Display |
|-------|-----------------|------------------|
| Reduction Value | `NaN%` | `30%`, `49%`, etc. |
| Prevented/yr | `—` | `134.1`, `219.5`, etc. |
| Rating | `undefined-sta☆` | `4-star · 2018` |
| Score Bar | `NaN` (no fill) | `361`, `349`, etc. |
| Why Recommended | 2 generic reasons | 5+ specific reasons |
| Crash Type Tags | Not shown | `angle`, `rear end`, etc. |
| Applicability | Not shown | `3-leg,4-leg`, `Lanes: 2-2` |
| View Study | Missing | Present |

---

## Root Cause Analysis

### 1. Missing Data Processing in AI Path

**File:** `index.html`
**Function:** `displayAIRecommendationsAsCards()` (Lines 17784-18026)

The AI card renderer doesn't calculate key metrics:
- No `expectedReduction` calculation (uses raw `crfPct` which may be missing)
- No `relevanceScore` computation
- No crash type matching logic
- Missing reasons generation from crash profile

**Contrast with:** `displayCMFRecommendations()` (Lines 19277-19553)
- Calculates `expectedReduction` from crash data
- Computes multi-tier `relevanceScore` (up to 260 points)
- Generates rich `relevanceReasons[]` array
- Matches crash types against profile

### 2. AI Found CMFs Missing Enrichment

**Issue Location:** Lines 17492-17506
```javascript
// After AI search, CMFs go directly to display
cmfState.aiFoundCMFs = searchResults;
displayAIRecommendationsAsCards(cmfState.aiFoundCMFs);
```

**Missing Step:** No enrichment with:
- Crash profile data for expected reduction calculation
- Relevance scoring algorithm
- Reason generation logic

### 3. Data Field Mapping Issues

| CMF Database Field | Expected Card Field | Issue |
|-------------------|---------------------|-------|
| `crfPct` | Reduction % | May be null/undefined |
| `rating` | Star rating | Not formatted properly |
| `pubYear` | Year | Not extracted |
| `standardError` | Confidence ±% | Not calculated |

---

## Implementation Plan

### Phase 1: Data Enrichment Function

**Create:** `enrichCMFWithCrashData(cmf, crashProfile)`

This function will add missing calculated fields to each CMF:

```javascript
function enrichCMFWithCrashData(cmf, crashProfile) {
  const enriched = { ...cmf };

  // 1. Calculate expected reduction per year
  enriched.expectedReduction = calculateExpectedReduction(cmf, crashProfile);

  // 2. Calculate relevance score using same algorithm as findCountermeasures()
  enriched.relevanceScore = calculateRelevanceScore(cmf, crashProfile);

  // 3. Generate relevance reasons
  enriched.relevanceReasons = generateRelevanceReasons(cmf, crashProfile);

  // 4. Identify matching crash types
  enriched.matchingTypes = findMatchingCrashTypes(cmf.crashTypes, crashProfile);

  // 5. Calculate cost tier
  enriched.costTier = determineCostTier(cmf);

  // 6. Calculate confidence interval
  enriched.confidenceInterval = calculateConfidence(cmf);

  return enriched;
}
```

### Phase 2: Expected Reduction Calculation

**Extract from:** `findCountermeasures()` (Lines 19220-19240)

Logic to replicate:
```javascript
function calculateExpectedReduction(cmf, crashProfile) {
  // Get CRF percentage (handle null/undefined)
  const crfPct = cmf.crfPct ?? (cmf.cmf ? (1 - cmf.cmf) * 100 : null);

  if (crfPct === null || !crashProfile) {
    return null;
  }

  // Calculate based on matching crash types
  let applicableCrashes = 0;

  if (cmf.crashTypes?.length > 0) {
    cmf.crashTypes.forEach(type => {
      const count = crashProfile.collisionTypes?.[type] || 0;
      applicableCrashes += count;
    });
  } else {
    applicableCrashes = crashProfile.total || 0;
  }

  // Expected crashes prevented per year
  const yearsOfData = crashProfile.years || 5;
  const annualCrashes = applicableCrashes / yearsOfData;
  const prevented = annualCrashes * (crfPct / 100);

  return prevented.toFixed(1);
}
```

### Phase 3: Relevance Score Calculation

**Extract from:** `findCountermeasures()` (Lines 18978-19210)

Create a shared scoring function:
```javascript
function calculateRelevanceScore(cmf, crashProfile, roadProperties) {
  let score = 0;

  // Tier 1: Primary Relevance (0-100 pts)
  score += scoreCrashTypeMatch(cmf, crashProfile);
  score += scoreLocationTypeMatch(cmf, roadProperties);

  // Tier 2: Evidence Quality (0-50 pts)
  score += (cmf.rating || 0) * 5;  // Up to 25 pts
  score += scoreRecency(cmf.pubYear);  // Up to 15 pts
  score += cmf.isProven ? 40 : 0;
  score += cmf.inHSM ? 15 : 0;

  // Tier 3: Contextual Matching (0-50 pts)
  score += cmf.isVirginia ? 25 : 0;
  score += scoreTrafficControlMatch(cmf, roadProperties);
  score += scoreFunctionalClassMatch(cmf, roadProperties);

  // Tier 4: Severity & Behavioral (0-60 pts)
  score += scoreSeverityMatch(cmf, crashProfile);
  score += scoreBehavioralMatch(cmf, crashProfile);

  return Math.min(score, 400); // Cap at max
}
```

### Phase 4: Relevance Reasons Generation

**Extract from:** `findCountermeasures()` (Lines 18850-19000)

```javascript
function generateRelevanceReasons(cmf, crashProfile, roadProperties) {
  const reasons = [];

  // AI-selected badge
  if (cmf.aiSelected) {
    reasons.push({ icon: '🤖', text: 'AI-selected based on crash patterns' });
  }

  // Evidence quality
  if (cmf.isProven) {
    reasons.push({ icon: '✅', text: 'FHWA Proven Safety Countermeasure' });
  }
  if (cmf.inHSM) {
    reasons.push({ icon: '📘', text: 'Highway Safety Manual listed' });
  }
  if (cmf.isVirginia) {
    reasons.push({ icon: '🅥', text: 'Virginia-specific study data' });
  }

  // Crash type matching
  const matchedTypes = findMatchingCrashTypes(cmf.crashTypes, crashProfile);
  if (matchedTypes.length > 0) {
    reasons.push({
      icon: '🎯',
      text: `Addresses ${matchedTypes.join(', ')} crashes`
    });
  }

  // Location matching
  if (roadProperties?.trafficControl &&
      cmf.trafficControl?.includes(roadProperties.trafficControl)) {
    reasons.push({ icon: '🚦', text: 'Matches signalized intersection' });
  }

  // Severity matching
  if (crashProfile?.k > 0 || crashProfile?.a > 0) {
    if (cmf.crashTypes?.some(t => ['fatal', 'serious'].includes(t.toLowerCase()))) {
      reasons.push({ icon: '⚠️', text: 'Addresses fatal/serious crash patterns' });
    }
  }

  // Behavioral factors
  if (crashProfile?.distracted > 0) {
    reasons.push({ icon: '📱', text: `${crashProfile.distracted}% distraction-involved` });
  }

  return reasons;
}
```

### Phase 5: Update AI Card Renderer

**Modify:** `displayAIRecommendationsAsCards()` (Lines 17784-18026)

Changes needed:

#### 5.1 Stats Grid Fix
```javascript
// Before (broken):
<div class="cmf-card-stat-value positive">${cmf.crfPct || 'NaN'}%</div>

// After (fixed):
<div class="cmf-card-stat-value positive">${enriched.crfPct?.toFixed(0) || 'N/A'}%</div>
<div class="cmf-card-stat-label">Reduction</div>

<div class="cmf-card-stat-value">${enriched.expectedReduction || '—'}</div>
<div class="cmf-card-stat-label">Prevented/yr</div>

<div class="cmf-card-stat-value">${enriched.confidenceInterval || 'Low'}</div>
<div class="cmf-card-stat-label">Confidence</div>

<div class="cmf-card-stat-value">${enriched.costTier || 'Medium'}</div>
<div class="cmf-card-stat-label">Cost Est.</div>
```

#### 5.2 Rating Display Fix
```javascript
// Before (broken):
${cmf.rating}-sta☆

// After (fixed):
${renderStarRating(cmf.rating)} · ${cmf.pubYear || 'N/A'}

function renderStarRating(rating) {
  const stars = Math.round(rating || 0);
  const filled = '★'.repeat(stars);
  const empty = '☆'.repeat(5 - stars);
  return `${stars}-star`;
}
```

#### 5.3 Relevance Bar Fix
```javascript
// Before (broken):
<div class="cmf-card-relevance-fill" style="width:${(cmf.relevance||0)*100}%"></div>
<span class="cmf-card-relevance-score">NaN</span>

// After (fixed):
<div class="cmf-card-relevance-fill" style="width:${(enriched.relevanceScore/400)*100}%"></div>
<span class="cmf-card-relevance-score">${enriched.relevanceScore}</span>
```

#### 5.4 Reasons Section Enhancement
```javascript
// Before (limited):
<div class="cmf-card-reason">🤖 AI-selected based on crash patterns</div>
<div class="cmf-card-reason">✅ FHWA Proven Safety Countermeasure</div>

// After (rich):
${enriched.relevanceReasons.map(r => `
  <div class="cmf-card-reason">${r.icon} ${r.text}</div>
`).join('')}
```

#### 5.5 Add Crash Type Tags
```javascript
// Add after reasons section:
<div class="cmf-card-tags">
  ${enriched.matchingTypes?.map(type => `
    <span class="cmf-card-tag matched">${type}</span>
  `).join('') || ''}
  ${(cmf.crashTypes || []).filter(t => !enriched.matchingTypes?.includes(t)).map(type => `
    <span class="cmf-card-tag">${type}</span>
  `).join('')}
</div>
```

#### 5.6 Add Applicability Info
```javascript
// Add before action buttons:
<div class="cmf-card-applicability">
  ${cmf.intersectionGeometry ? `
    <span class="cmf-card-tag">${cmf.intersectionGeometry}</span>
  ` : ''}
  ${cmf.minLanes || cmf.maxLanes ? `
    <span class="cmf-card-tag">Lanes: ${cmf.minLanes || '?'}-${cmf.maxLanes || '?'}</span>
  ` : ''}
</div>
```

#### 5.7 Add View Study Button
```javascript
// Add to action buttons:
${cmf.studyLink ? `
  <a href="${cmf.studyLink}" target="_blank" class="cmf-card-action-btn secondary">
    📖 View Study
  </a>
` : ''}
```

### Phase 6: Integration Point

**Modify:** Lines 17492-17506

```javascript
// Before:
cmfState.aiFoundCMFs = searchResults;
displayAIRecommendationsAsCards(cmfState.aiFoundCMFs);

// After:
cmfState.aiFoundCMFs = searchResults.map(cmf =>
  enrichCMFWithCrashData(cmf, cmfState.crashProfile, cmfState.roadProperties)
);
displayAIRecommendationsAsCards(cmfState.aiFoundCMFs);
```

---

## Shared Utility Functions

To avoid code duplication, extract these into shared utilities:

1. `enrichCMFWithCrashData(cmf, crashProfile, roadProperties)`
2. `calculateExpectedReduction(cmf, crashProfile)`
3. `calculateRelevanceScore(cmf, crashProfile, roadProperties)`
4. `generateRelevanceReasons(cmf, crashProfile, roadProperties)`
5. `findMatchingCrashTypes(cmfTypes, crashProfile)`
6. `determineCostTier(cmf)`
7. `calculateConfidence(cmf)`
8. `renderStarRating(rating, year)`

---

## Implementation Order

1. **Step 1:** Create shared utility functions (extract from existing algo code)
2. **Step 2:** Create `enrichCMFWithCrashData()` wrapper function
3. **Step 3:** Integrate enrichment into AI flow (Line 17492)
4. **Step 4:** Update `displayAIRecommendationsAsCards()` template
5. **Step 5:** Add View Study button and applicability info
6. **Step 6:** Test with various crash profiles

---

## Testing Checklist

- [ ] Reduction % shows actual numbers (not NaN)
- [ ] Prevented/yr shows calculated values
- [ ] Star rating displays correctly with year
- [ ] Relevance bar fills with actual score
- [ ] "Why Recommended" shows 3-5+ relevant reasons
- [ ] Crash type tags appear with matching highlighted
- [ ] Applicability info (lanes, intersection type) shows
- [ ] View Study button appears when studyLink exists
- [ ] Cards match visual style of algorithmic cards
- [ ] High-relevance cards get green border styling

---

## Files to Modify

| File | Lines | Changes |
|------|-------|---------|
| `index.html` | 17492-17506 | Add enrichment call |
| `index.html` | 17784-18026 | Update card template |
| `index.html` | ~17780 | Add utility functions |

---

## Visual Mockup (Expected Result)

```
┌─────────────────────────────────────────────────────────────┐
│ [Intersection traffic control] [🚦 INT] [✓ PROVEN]  ★★★★☆  │
│                                                    4-star · 2018
│                                                             │
│ Changing left turn phasing from protected-permissive        │
│ to flashing yellow arrow (FYA)                              │
│                                                             │
│ ┌──────────┬──────────┬──────────┬──────────┐              │
│ │   30%    │  134.1   │   High   │  Medium  │              │
│ │ Reduction│Prevented/│Confidence│ Cost Est.│              │
│ │          │    yr    │   ±13%   │          │              │
│ └──────────┴──────────┴──────────┴──────────┘              │
│                                                             │
│ ████████████████████████████░░░░░░░░░░░░░  361              │
│                                                             │
│ Why Recommended                                             │
│ 🤖 AI-selected based on crash patterns                      │
│ ✅ FHWA Proven Safety Countermeasure                        │
│ 🅥 Virginia-specific study data                             │
│ 🎯 Addresses angle crashes                                  │
│ 🚦 Matches signalized intersection                          │
│                                                             │
│ [angle] [3-leg,4-leg]                                       │
│                                                             │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐           │
│ │📖 View  │ │📋 Copy  │ │🤖 Ask AI│ │📕 Ask    │           │
│ │  Study  │ │         │ │         │ │   MUTCD  │           │
│ └─────────┘ └─────────┘ └─────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────┘
```

---

## Summary

The main issue is that `displayAIRecommendationsAsCards()` uses raw CMF data without enrichment, while `displayCMFRecommendations()` applies extensive calculations and scoring.

The fix is to:
1. Extract shared calculation logic into utility functions
2. Apply enrichment to AI results before rendering
3. Update the AI card template to match the algorithmic template

This will ensure both card types display the same rich, informative data.
