# Plan: Relocate Find Countermeasures / AI Recommended Buttons

## Problem Statement

Currently, the "Find Countermeasures" and "AI Recommended" toggle buttons are positioned **before** the advanced filter options. This creates a suboptimal user experience because:

1. Users may click the action buttons before setting important filters
2. Advanced filters (Number of Lanes, Intersection Geometry, Road Division, AADT) directly affect result accuracy
3. The checkbox options (FHWA Proven Only, HSM Only, Virginia First) are easy to miss

## Current Layout Order (index.html lines 1935-2178)

```
1. Search by Road Name input + Go/Map buttons
2. Basic Filters Row:
   - Or Select Location dropdown
   - Location Type
   - Area Type
   - Min Star Rating
3. TOGGLE BUTTONS ← Current position (lines 1989-1991)
   - Find Countermeasures
   - AI Recommended
4. AI Configuration Popover (lines 1993-2018)
5. Advanced Filters Row (lines 2022-2079):
   - Number of Lanes
   - Intersection Geometry
   - Road Division
   - AADT (vpd)
   - Checkboxes (FHWA Proven Only, HSM Only, Virginia First)
6. Results Sections (conditionally displayed)
```

## Proposed Layout Order

```
1. Search by Road Name input + Go/Map buttons
2. Basic Filters Row:
   - Or Select Location dropdown
   - Location Type
   - Area Type
   - Min Star Rating
3. Advanced Filters Row:
   - Number of Lanes
   - Intersection Geometry
   - Road Division
   - AADT (vpd)
   - Checkboxes (FHWA Proven Only, HSM Only, Virginia First)
4. TOGGLE BUTTONS ← New position (after all filters)
   - Find Countermeasures
   - AI Recommended
5. AI Configuration Popover
6. Results Sections (conditionally displayed)
```

## Implementation Steps

### Step 1: Move Button Toggle Group
- Relocate the `cmf-toggle-group` div (lines 1989-1991) from its current position
- Place it immediately after the advanced filters section (after line 2079)
- The AI Configuration Popover (lines 1993-2018) should move with the buttons

### Step 2: Adjust Styling
- Review the dashed border styling on the advanced filters row
- Consider removing or relocating the visual separator
- Ensure the button group has appropriate spacing from the filters above

### Step 3: Update Visual Hierarchy
- The buttons should remain prominent and easily discoverable
- Consider adding a subtle visual indicator that filters have been applied
- Maintain the existing active/inactive button states

### Step 4: Test Functionality
- Verify `setCMFMode('algo')` and `setCMFMode('ai')` functions still work
- Confirm AI configuration popover positioning works correctly in new location
- Test on mobile and desktop viewports
- Verify result caching behavior is unaffected

## Files to Modify

1. **index.html** (lines ~1989-2079)
   - Move button toggle group div
   - Move AI configuration popover
   - Adjust any separator elements

2. **styles.css** (if needed)
   - Update any positional styling
   - Adjust spacing/margins as needed

## UX Benefits

1. **Natural workflow**: Users set all filters before executing search
2. **Improved accuracy**: Less likely to get irrelevant results from default filters
3. **Clearer hierarchy**: Action buttons at the end signal "click when ready"
4. **Reduced friction**: Matches common form patterns (inputs first, submit last)

## Risk Assessment

- **Low risk**: UI-only change, no business logic modifications
- **Backward compatible**: No API or data structure changes
- **Reversible**: Easy to revert if needed
