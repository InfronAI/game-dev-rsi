// Emit the state seen by a player after start and after each input.
import {pathToFileURL} from "node:url";
import {readFileSync} from "node:fs";
const game = await import(pathToFileURL(process.argv[2]));
const actions = JSON.parse(readFileSync(0, "utf8"));
let state = game.start();
const snapshots = [];
function capture() {
  if (!state || !Number.isInteger(state.x) || !Number.isInteger(state.y) ||
      !Number.isInteger(state.power) || !Array.isArray(state.relays) ||
      !state.relays.every(item => typeof item === "string") ||
      !["active", "won", "drained"].includes(state.phase)) throw Error("Invalid game state");
  snapshots.push(structuredClone(state));
}
capture();
for (const input of actions) { state = game.step(state, input); capture(); }
process.stdout.write(JSON.stringify(snapshots));
