import { immichIdFrom } from "./actions";

describe("immichIdFrom", () => {
  it("takes the photo id, the last UUID of the link", () => {
    expect(
      immichIdFrom(
        "https://fotos.example/albums/11111111-2222-3333-4444-555555555555/photos/AAAAAAAA-bbbb-cccc-dddd-eeeeeeeeeeee",
      ),
    ).toBe("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    expect(immichIdFrom("nada")).toBeNull();
  });
});
