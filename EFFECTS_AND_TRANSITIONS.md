# Available Effects and Transitions

This document lists the available visual effects and transitions supported by the `/generate-video` endpoint.

## 1. Visual Effects (Applied to individual images)

Define these in the `effect` object within each image item in your JSON configuration.

| Effect Type | Description | Parameters | Default Values |
| :--- | :--- | :--- | :--- |
| **`none`** | Static image. | None | N/A |
| **`zoom_slow`** | Ken Burns style slow zoom. | `zoom_start`<br>`zoom_end`<br>`zoom_step` | `1.0`<br>`1.15`<br>`0.0015` |
| **`cinematic_motion`** | Cinematic motion with easing curves (ease in/out). | `movement`<br>`intensity` | `push_in`<br>`medium` |
| **`perspective_camera`** | 3D perspective shift on corners for dynamic look. | `movement`<br>`intensity` | `drift_right`<br>`medium` |
| **`depth_parallax`** | True 2.5D depth parallax using AI depth maps. | `movement`<br>`intensity` | `move_left`<br>`medium` |
| **`fade`** | Fades the image in/out. | `fade_in` (obj)<br>`fade_out` (obj) | `start_time: 0.0`, `duration: 0.5` |
| **`slide_horizontal`** | Reveals image horizontally via a gradient mask. | `direction` | `left_to_center`, `right_to_center`, `right_to_left`, `left_to_right` |
| **`slide_vertical`** | Reveals image vertically via a gradient mask. | `direction` | `bottom_to_top`, `top_to_bottom` |
| **`pan`** | Smooth lateral movement (no zoom). | `direction`, `speed` | `left_to_right`, `10` |
| **`parallax_fake`** | Blurred moving background with different foreground speed. | `bg_speed`, `fg_speed`, `blur`, `scale` | `5`, `15`, `15`, `1.15` |
| **`focus_reveal`** | Progressive blur to sharp reveal mask. | `direction`, `blur_strength`, `softness` | `left_to_right`, `12`, `0.3` |
| **`zoom_pan`** | Cinematic zoom with lateral pan (modern Ken Burns). | `zoom_start`, `zoom_end`, `direction` | `1.0`, `1.08`, `left_to_right` |
| **`micro_motion`** | Very subtle zoom and pan. | None | N/A |
| **`vignette_motion`** | Subtle zoom with slowly pulsating vignette. | None | N/A |
| **`light_sweep`** | Instagram style sweeping bright light. | `width`, `intensity` | `0.2`, `0.3` |
| **`focus_pull`** | Cinematographic blur in/out over duration. | `blur_start`, `blur_end` | `15`, `0` |
| **`rgb_split`** | Subtle RGB color separation on borders. | None | N/A |
| **`film_grain`** | Adds uniform film grain texture over duration. | None | N/A |
| **`letterbox`** | Adds cinematic black borders (top/bottom). | None | N/A |
| **`speed_ramp`** | Non-linear easing zoom speed ramp. | `zoom_end` | `1.15` |

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
| **`slide`** | Slides the next image in over the current one. | `direction` (`left`, `right`, `up`, `down`) |
| **`wipe`** | Clean sweep reveal. | `direction` (`left`, `right`, `up`, `down`) |
| **`zoom`** | Zooms camera to transition. | `direction` (`in`, `out`) |
| **`fade_color`** | Fades through a solid color. | `color` (`black`, `white`) |
| **`blur_transition`** | Smooth fade out/in cross-blur. | None |
| **`directional_blur`** | Sliding motion blur. | `direction` (`left`, `right`, `up`, `down`) |
| **`mask`** | Shape-based transition masking. | `shape` (`radial`, `diagonal`, `gradient`) |
| **`spin`** | Spinning or swirling transition. | `style` (`rotate`, `swirl`) |
| **`glitch`** | RGB color shift during transition. | None |
| **`cross_zoom`** | Strong kinematic zoom with extreme blur pass. | None |

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
