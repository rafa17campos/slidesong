import { namedIn } from "./Chooser";

describe("namedIn", () => {
  const people = [{ name: "Iker" }, { name: "Nico" }, { name: "Eva Ruiz" }, { name: "Mar" }];
  it("finds people named in the line as whole, capitalised words", () => {
    expect(namedIn("y por la tarde llegaron Iker y Bruno,", people)).toEqual(["Iker"]);
    expect(namedIn("Nico corría por la arena", people)).toEqual(["Nico"]);
    expect(namedIn("vimos el mar", people)).toEqual([]);
    expect(namedIn("Con Eva Ruiz en la playa", people)).toEqual(["Eva Ruiz"]);
  });
});
