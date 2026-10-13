export const initialPilotState = {open: false, visited: false, layout: null, selectedId: null, view: "map"};

// Owned by the dashboard, independently of its zone-details drawer.
export function pilotReducer(state, action) {
  switch (action.type) {
    case "open": return {...state, open: true, visited: true};
    case "close": return {...state, open: false};
    case "loaded": return {...state, layout: action.layout, selectedId: state.selectedId || action.layout.my_slot_id || null};
    case "select": return {...state, selectedId: action.slotId};
    case "view": return {...state, view: action.view};
    case "updated": return {...state, layout: {...state.layout, slots: state.layout.slots.map(slot => slot.slot_id === action.slot.slot_id ? action.slot : slot)}};
    default: return state;
  }
}
