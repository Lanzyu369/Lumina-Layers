#include <lunasvg.h>

#include <cmath>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>

namespace {

int fail(const std::string &reason) {
  std::cerr << reason << '\n';
  return 1;
}

bool parseDimension(const char *value, int &destination) {
  try {
    const auto parsed = std::stoul(value);
    if (parsed == 0 ||
        parsed > static_cast<unsigned long>(std::numeric_limits<int>::max()))
      return false;
    destination = static_cast<int>(parsed);
    return true;
  } catch (const std::exception &) {
    return false;
  }
}

bool parseFinite(const char *value, double &destination) {
  try {
    size_t consumed = 0;
    destination = std::stod(value, &consumed);
    return consumed == std::string(value).size() && std::isfinite(destination);
  } catch (const std::exception &) {
    return false;
  }
}

} // namespace

int main(int argc, char **argv) {
  if (argc != 9) {
    return fail("usage: raster-oracle INPUT.svg OUTPUT.rgba WIDTH HEIGHT "
                "BBOX_X BBOX_Y BBOX_WIDTH BBOX_HEIGHT");
  }

  int width = 0;
  int height = 0;
  if (!parseDimension(argv[3], width) || !parseDimension(argv[4], height))
    return fail("invalid_dimensions");
  double bboxX = 0;
  double bboxY = 0;
  double bboxWidth = 0;
  double bboxHeight = 0;
  if (!parseFinite(argv[5], bboxX) || !parseFinite(argv[6], bboxY) ||
      !parseFinite(argv[7], bboxWidth) || !parseFinite(argv[8], bboxHeight) ||
      !(bboxWidth > 0) || !(bboxHeight > 0))
    return fail("invalid_bbox");

  auto document = lunasvg::Document::loadFromFile(argv[1]);
  if (document == nullptr)
    return fail("invalid_svg");
  lunasvg::Bitmap bitmap(width, height);
  if (bitmap.isNull())
    return fail("render_failed");
  bitmap.clear(UINT32_C(0x00000000));
  const double scaleX = static_cast<double>(width) / bboxWidth;
  const double scaleY = static_cast<double>(height) / bboxHeight;
  document->render(bitmap, lunasvg::Matrix(scaleX, 0, 0, scaleY,
                                           -bboxX * scaleX, -bboxY * scaleY));
  bitmap.convertToRGBA();
  std::ofstream output(argv[2], std::ios::binary | std::ios::trunc);
  if (!output)
    return fail("output_open_failed");
  for (int y = 0; y < height; ++y) {
    const auto *row = bitmap.data() + static_cast<size_t>(y) *
                                          static_cast<size_t>(bitmap.stride());
    output.write(reinterpret_cast<const char *>(row),
                 static_cast<std::streamsize>(width) * 4);
  }
  if (!output)
    return fail("output_write_failed");
  return 0;
}
