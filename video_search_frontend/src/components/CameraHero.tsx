/**
 * Camera portrait for the Upload hero's left column — the real asset at
 * public/cameraside.png (already shot in the same moody, single-light-source
 * style as the rest of the product: gold key light, black background, a
 * thread of light swirling toward a galaxy). The edges are feathered with a
 * radial mask so the photo's black background dissolves into the page's own
 * dark background instead of sitting in a visible rectangle, and the crop is
 * weighted toward the right so the galaxy — which visually points at the
 * headline/upload area — stays in frame.
 */
export function CameraHero() {
  return (
    <div className="relative flex w-full max-w-md items-center justify-center md:max-w-xl">
      <div className="pointer-events-none absolute h-2/3 w-2/3 rounded-full bg-glow/10 blur-3xl" />
      <img
        src="/cameraside.png"
        alt="Security camera, lens open, a thread of light trailing off toward a distant galaxy"
        className="relative w-full [mask-image:radial-gradient(ellipse_75%_75%_at_45%_50%,black_55%,transparent_100%)] [-webkit-mask-image:radial-gradient(ellipse_75%_75%_at_45%_50%,black_55%,transparent_100%)]"
      />
    </div>
  )
}
