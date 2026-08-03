template <typename T>
constexpr T square(T value) {
  return value * value;
}

int use_square(int value) {
  return square(value);
}
