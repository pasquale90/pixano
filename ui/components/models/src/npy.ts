const dtypes = {
  "<u1": {
    name: "uint8",
    size: 8,
    arrayConstructor: Uint8Array,
  },
  "|u1": {
    name: "uint8",
    size: 8,
    arrayConstructor: Uint8Array,
  },
  "<u2": {
    name: "uint16",
    size: 16,
    arrayConstructor: Uint16Array,
  },
  "|i1": {
    name: "int8",
    size: 8,
    arrayConstructor: Int8Array,
  },
  "<i2": {
    name: "int16",
    size: 16,
    arrayConstructor: Int16Array,
  },
  "<u4": {
    name: "uint32",
    size: 32,
    arrayConstructor: Int32Array,
  },
  "<i4": {
    name: "int32",
    size: 32,
    arrayConstructor: Int32Array,
  },
  "<u8": {
    name: "uint64",
    size: 64,
    arrayConstructor: BigUint64Array,
  },
  "<i8": {
    name: "int64",
    size: 64,
    arrayConstructor: BigInt64Array,
  },
  "<f4": {
    name: "float32",
    size: 32,
    arrayConstructor: Float32Array,
  },
  "<f8": {
    name: "float64",
    size: 64,
    arrayConstructor: Float64Array,
  },
};

export function parse(buffer) {
  const buf = new Uint8Array(buffer);
  if (buf[6] != 1) throw "Only npy version 1 is supported";

  const headerLength = buf[8] + buf[9] * 256;
  const offsetBytes = 10 + headerLength;

  const header = JSON.parse(
    new TextDecoder("utf-8")
      .decode(buf.slice(10, 10 + headerLength))
      .replace(/'/g, '"')
      .replace("False", "false")
      .replace("(", "[")
      .replace(/,*\),*/g, "]")
  );

  if (header.fortan_order)
    throw "Fortran-contiguous array data are not supported";
  const dtype = dtypes[header.descr];

  return {
    data: new dtype["arrayConstructor"](buf.slice(offsetBytes).buffer),
    shape: header.shape,
    dtype: dtype.name,
  };
}
