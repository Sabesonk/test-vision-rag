// jsdom implements neither of the two browser APIs the viewer depends on, and both are load
// bearing: `scrollIntoView` is how clicking a code reaches its cited page, and the object-URL
// pair is how an authenticated raster becomes an `<img src>` without the token ever appearing in
// a URL. Stubbing them here rather than in each test keeps the assertions about *our* behaviour.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView(): void {}
}

let issued = 0
if (!URL.createObjectURL) {
  URL.createObjectURL = () => `blob:vsir/${++issued}`
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = () => {}
}
