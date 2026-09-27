# T05 — Extract a unit-testable `FrameConverter`

Status: open

| | |
|---|---|
| Fixes | Preparation for [DP01](../gym_data_path_review.md#dp01--torn-frames), [DP02](../gym_data_path_review.md#dp02--resolution-changes-arent-handled-on-the-agent-path), [DP10](../gym_data_path_review.md#dp10--aliased-downscaling-and-wasted-conversion) |
| Priority / size | P0 / M |
| Depends on | T01 |
| Area | C++: new `src/video/frame_converter.{hpp,cpp}` |
| Needs a device | No |

## Why

Three findings live in the same few lines of `Decoder::Push` (`src/video/decoder.cpp:102-154`) and
`ai::ConvertToMat` (`src/ai/brain.cpp:27-45`):
- the conversion runs without the lock (DP01);
- it's set up once and never rebuilt (DP02);
- it converts at full size with a filter that aliases (DP10).

None of that code has tests, because it's tangled up with the decoder and needs a real video stream.

This task builds the replacement as a small, self-contained class with tests. **It doesn't change
any production code path yet.** T06 wires it in. Keeping them separate means this PR can be
reviewed purely on "does the converter do the right thing".

## What to build

`src/video/frame_converter.hpp`:

```cpp
namespace irobot::video
{
    enum class ConvertedFormat { Bgr24, Gray8 };

    // Converts decoded video frames into OpenCV images of a requested size.
    // Keeps one swscale context and rebuilds it only when the source size/format or the requested
    // output changes. Not thread-safe: use one instance per thread (or guard it with a lock).
    class FrameConverter
    {
    public:
        FrameConverter() = default;
        ~FrameConverter();
        FrameConverter(const FrameConverter&) = delete;
        FrameConverter& operator=(const FrameConverter&) = delete;

        // Returns an empty cv::Mat if src is null, has no data, or has a zero dimension.
        // dst_width/dst_height must be > 0.
        cv::Mat Convert(const AVFrame* src, int dst_width, int dst_height, ConvertedFormat format);

        // Size that fits src inside max_side on its longer edge, keeping aspect ratio,
        // with each side at least 1. Returns {0, 0} if src_width or src_height <= 0.
        static cv::Size FitWithin(int src_width, int src_height, int max_side);
    };
}
```

Implementation notes for `frame_converter.cpp`:

1. Use `sws_getCachedContext(...)`. It returns the existing context when nothing changed and
   rebuilds it when anything did. That's what makes rotation "just work" later (T07).
2. Take the source pixel format from `src->format`. Don't hard-code `AV_PIX_FMT_YUV420P` the way
   `decoder.cpp:106` does.
3. Output formats: `AV_PIX_FMT_BGR24` into a `CV_8UC3` mat, and `AV_PIX_FMT_GRAY8` into a `CV_8UC1`
   mat. Allocate the `cv::Mat` first and pass `mat.data` and `(int)mat.step` as the destination
   plane and stride to `sws_scale`.
4. Scaling flag: use `SWS_AREA` when the output is smaller than the source in both dimensions (area
   averaging, which is what fixes the aliasing in DP10), and `SWS_BILINEAR` otherwise.
5. Free the context in the destructor with `sws_freeContext`.
6. Add the `.cpp` to `COMMON_SOURCES` in the top-level `CMakeLists.txt` (line 88), next to
   `decoder.cpp`.

## Tests

Create `tests/test_frame_converter.cpp` (add it to `TEST_SOURCE` in `tests/CMakeLists.txt`), tagged
`[video][converter]`. Write a small helper that makes a YUV420P `AVFrame` with `av_frame_alloc()`,
sets `format`, `width` and `height`, calls `av_frame_get_buffer(frame, 0)`, and fills the Y, U and V
planes (remember each plane has its own `linesize`).

1. **Colours.** Solid frames using BT.601 limited-range values convert to the expected BGR, within
   ±12 per channel:

   | Frame | Y | U | V | Expected BGR (approx.) |
   |---|---|---|---|---|
   | Grey | 126 | 128 | 128 | (128, 128, 128) |
   | Red | 81 | 90 | 240 | (0, 0, 255) |
   | Green | 145 | 54 | 34 | (0, 255, 0) |
   | Blue | 41 | 240 | 110 | (255, 0, 0) |

   If your results are consistently off, check that swscale treats the input as limited range
   (it should, by default) before adjusting the table, and explain any change in the PR.
2. **Gray8 output** of the grey frame is a single-channel mat with values around 128.
3. **`FitWithin`:** 2670×1200 → max 800 gives 800×360; 1200×2670 → max 240 gives 108×240;
   0×0 gives 0×0.
4. **Size change.** Convert a 1200×2670 frame, then a 2670×1200 frame with the same instance. Both
   outputs have the requested sizes and correct colours. Run this one under AddressSanitizer at
   least once locally (see the [README](README.md#build-and-test-commands)) and say so in the PR.
5. **Empty input.** A null frame, or a frame with `width == 0`, returns an empty mat without
   throwing.
6. **Small objects survive downscaling** (the DP10 regression test). Build 24 frames of 2670×1200
   black (Y=16) with a 6×6 white (Y=235) square at x = 1000 + i, for i in 0..23. Convert each to
   Gray8 at `FitWithin(2670, 1200, 240)`. Sum each output's pixels minus the black background
   (`sum - 16 * pixel_count`, roughly). Assert that the smallest sum is at least half the largest.
   With bilinear filtering the smallest is 0, meaning the object vanishes; area averaging keeps it
   stable (see the review's measurements).

## Done when

- All six tests pass locally and in CI.
- No production file other than `CMakeLists.txt` changed.
- The PR description includes the colour values your test actually measured, so reviewers can see
  the margins.
