# Available Effects and Transitions

This document lists the available visual effects and transitions supported by the `/generate-video` endpoint.

## 1. Visual Effects (Applied to individual images)

Define these in the `effect` object within each image item in your JSON configuration.

| Effect Type | Description | Parameters | Default Values |
| :--- | :--- | :--- | :--- |
| **`none`** | Static image. | None | N/A |
| **`zoom_slow`** | Ken Burns style slow zoom. | `zoom_start`<br>`zoom_end`<br>`zoom_step` | `1.0`<br>`1.15`<br>`0.0015` |
| **`fade`** | Fades the image in/out. | `fade_in` (obj)<br>`fade_out` (obj) | `start_time: 0.0`, `duration: 0.5` |
| **`slide_horizontal`** | Pans horizontally. | `direction` | `left_to_center`, `right_to_center`, `right_to_left`, `left_to_right` |
| **`slide_vertical`** | Pans vertically. | `direction`<br>`source_scale_height` | `bottom_to_top`, `top_to_bottom`<br>`1.25 * height` |

### JSON Example for Effects
```json
{
  "effect": {
    "type": "zoom_slow",
    "zoom_start": 1.0,
    "zoom_end": 1.2
  }
}
```

## 2. Transitions (Between images)

Define these in the `transition_to_next` object.

| Transition Type | Description | Parameters |
| :--- | :--- | :--- |
| **`none`** | Instant cut. | `None` |
| **`xfade`** | FFmpeg xfade transitions. | `transition` (string)<br>`duration` (float) |

### Supported `xfade` Transitions
You can use any standard FFmpeg xfade transition name, including:
- `fade` (default)
- `wipeleft`, `wiperight`, `wipeup`, `wipedown`
- `slideleft`, `slideright`, `slideup`, `slidedown`
- `circlecrop`, `rectcrop`
- `distance`, `iris`, `radial`
- `smoothleft`, `smoothright`, `smoothup`, `smoothdown`
- `pixelize`

### JSON Example for Transitions
```json
{
  "transition_to_next": {
    "type": "xfade",
    "transition": "wipeleft",
    "duration": 1.0
  }
}
```
