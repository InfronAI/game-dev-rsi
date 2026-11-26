// The browser and the paired replay collector import this same transition function.
export const map = ["#######", "#S*..E#", "#.#.#.#", "#....*#", "#######"];
export const requiredRelays = 2;
export const wallCost = 0;
const vectors = {up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0]};

export function start() {
  return {x: 1, y: 1, power: 12, relays: [], phase: "active"};
}

export function step(state, action) {
  if (action === "reset") return start();
  if (state.phase !== "active" || !Object.hasOwn(vectors, action)) return state;

  const [dx, dy] = vectors[action];
  const x = state.x + dx, y = state.y + dy;
  const tile = map[y][x];
  const blocked = tile === "#" || (tile === "E" && state.relays.length < requiredRelays);
  const next = {...state, relays: [...state.relays]};
  if (blocked) {
    next.power -= wallCost;
  } else {
    next.x = x;
    next.y = y;
    next.power -= 1;
    const id = x + "," + y;
    if (tile === "*" && !next.relays.includes(id)) next.relays.push(id);
    if (tile === "E") next.phase = "won";
  }
  if (next.power === 0 && next.phase === "active") next.phase = "drained";
  return next;
}
