import test from "node:test";
import assert from "node:assert/strict";
import {start, step} from "../cases/relay-vault/assets/reference/logic.mjs";

function replay(sequence) {
  const keys={R:"right",L:"left",U:"up",D:"down",X:"reset"};
  return [...sequence].reduce((state,key)=>step(state,keys[key]),start());
}
test("blocked walls and exits consume no power", () => {
  assert.deepEqual(replay("UL"),start());
  assert.deepEqual(replay("RRRR"),replay("RRR"));
});
test("revisiting a relay does not duplicate it", () => assert.deepEqual(replay("RLR").relays,["2,1"]));
test("last charge wins and terminal input is ignored", () => {
  const win=replay("RLRLRRDDRRUU");
  assert.equal(win.power,0);assert.equal(win.phase,"won");assert.deepEqual(step(win,"left"),win);
});
test("exhaustion is terminal and reset starts a fresh session", () => {
  const exhausted=replay("RLRLRLRLRLRL");assert.equal(exhausted.phase,"drained");
  assert.deepEqual(step(exhausted,"right"),exhausted);
  assert.deepEqual(step(exhausted,"reset"),start());
});
