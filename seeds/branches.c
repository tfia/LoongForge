enum mode {
  MODE_ADD,
  MODE_SUB,
  MODE_MUL
};

long calculate(enum mode operation, long left, long right) {
  switch (operation) {
    case MODE_ADD:
      return left + right;
    case MODE_SUB:
      return left - right;
    case MODE_MUL:
      return left * right;
  }
  return 0;
}
