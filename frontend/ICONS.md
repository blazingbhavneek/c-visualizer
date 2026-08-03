# Daemon entity icons

Resources on the ground plane are drawn with a shape that says what kind of
thing they are, before the colour or the label is read. Files are a database
drum, queues are three stacked slots, everything else is still a disc.

## Where a kind comes from

The kind is decided by the analyzer, not the frontend: `_resource_kind()` in
`visualizer_export.py` maps the traced operation onto one of

| kind | produced by |
|---|---|
| `file` | `OPENF`, `CLOSEF`, anything ending in `F` |
| `queue` | `ENQ`, `DEQ`, `ENQFORK`, `ENQSEM`, anything ending in `Q` |
| `event` | `EVENT` |
| `semaphore` | `SEMAPHORE` |
| `process` | `FORK`, `FORKP`, `KILL` |
| `message` | `MESSAGE` |
| `daemon_resource` | anything else |

A kind with no icon falls back to a disc, so adding a new operation type never
breaks the drawing — it just looks generic until you give it a shape.

## Adding an icon

Everything lives in `frontend/src/scene/icons.js`. Write a function that returns
an array of `THREE.Shape`, authored **at radius 1** in the local XY plane, then
register it:

```js
/** Semaphore: a flag on a post. */
function semaphoreShape() {
  const post = new THREE.Shape();
  post.moveTo(-0.12, -1);
  post.lineTo(0.12, -1);
  post.lineTo(0.12, 1);
  post.lineTo(-0.12, 1);
  post.closePath();

  const flag = new THREE.Shape();
  flag.moveTo(0.12, 1);
  flag.lineTo(0.95, 0.6);
  flag.lineTo(0.12, 0.2);
  flag.closePath();

  return [post, flag];
}

const ICON_SHAPES = {
  file: databaseShape,
  queue: queueShape,
  semaphore: semaphoreShape, // <- new
};
```

That is the whole change: `createResourceMark(kind, ...)` picks the builder up
by name and `buildOverview.js` already calls it for every resource.

## Rules an icon has to follow

These are not style preferences — the scene breaks without them.

1. **One mesh, one material.** Return several shapes if you like; they are
   compiled into a single `ShapeGeometry`. Picking raycasts non-recursively, and
   dimming multiplies one `material.opacity`, so a `THREE.Group` would be
   unpickable and would not fade.
2. **Flat, in XY, z = 0.** A plane seen edge-on has to collapse to a line; that
   is how the app declutters. Nothing may have depth.
3. **Author at radius 1.** The caller scales by `RESOURCE_RADIUS`. Keep the
   shape inside roughly ±1 or it will collide with its own label.
4. **Do not overlap sub-shapes.** Unresolved resources are drawn at 30%
   opacity, and overlapping translucent faces show as darker patches.
5. **Silhouette only.** One colour per mark: the fill comes from
   `RESOURCE_COLORS[kind]` in `palette.js`, and the ring around it already
   encodes "unresolved" and "shared".

## Colour and legend

A new kind usually wants an entry in `RESOURCE_COLORS` (`palette.js`) too —
without one it inherits the fallback slate. The palette notes in that file
explain why the existing hues were picked; keep new ones at a similar lightness
so they clear the white surface, and remember the label under every node spells
the kind out, so hue is a scanning aid rather than the encoding.
