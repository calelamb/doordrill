# Design Debt & UI Improvements

Based on the initial QA walkthrough of the DoorDrill Manager and Rep Consoles, the following CSS, layout, and user experience (UX) improvements are needed.

## Visual Hierarchy & Contrast

- [ ] **Low Contrast Backgrounds**: The layout uses a beige background with off-white cards, which results in a visually flat experience.
  - *Fix*: Increase the contrast between the main background and the card surfaces. Implement a subtle drop shadow on cards or slightly darken the container background.
- [ ] **Input Field Prominence**: Text input fields (like Manager ID and Rep ID) blend too much into the card backgrounds.
  - *Fix*: Give input fields a distinctly different background color (e.g., solid white), a subtle inner shadow, or a more defined border so they are clearly recognizable as interactive elements.
- [ ] **Missing Modern Aesthetics**: The current design lacks premium aesthetic touches.
  - *Fix*: Introduce glassmorphism (translucency and background blur) on floating elements or cards, and consider applying a modern, cohesive color palette (e.g., specific HSL values rather than default hex colors).

## Layout & Structure

- [ ] **Information Density in Manager Performance Panel**: The `Performance` section in the Manager Console merges Analytics, Rep Progress, and Manager Actions into a single, dense card.
  - *Fix*: Break these sub-sections out into a structured CSS Grid (e.g., a Bento grid layout). Ensure consistent padding and margin (gap) between these disparate pieces of data.
- [ ] **Inconsistent Padding**: Check and standardize the internal padding of cards and the margins separating them to ensure a uniform rhythm across the UI.
  - *Fix*: Define a standard spacing interval (e.g., utilizing a spacing scale in CSS variables) and apply it consistently to all `.card` or container classes.

## Interaction & State Management (UX Dead Ends)

- [ ] **Missing Loading States**: Action buttons like `Load Feed` and `Load Assignments` offer no visual feedback when clicked.
  - *Fix*: Implement loading spinners or skeleton loaders that trigger during the simulated data fetch process. Disable buttons while loading to prevent double-clicks.
- [ ] **Lack of Empty/Error State Messaging**: When entering an ID that yields no data, the UI remains fully static rather than informing the user.
  - *Fix*: Add toast notifications or inline error messages (e.g., "Manager ID not found" or "Network Error") when no data is returned.
- [ ] **Disconnected State Clarity**: The `Connect` button in the Rep Console does not visually indicate why it might not be working or what is required to connect.
  - *Fix*: Use a tooltip or a clearer disabled state for the button if the prerequisites for connecting (like a running WebSocket server or valid ID) aren't met.

## Micro-Interactions

- [ ] **Missing Hover States**: Interactive elements (buttons, inputs, potentially clickable cards) lack hover state definitions.
  - *Fix*: Add subtle CSS transitions (`transition: all 0.2s ease;`) on hover and active states to make the application feel more responsive and alive.
