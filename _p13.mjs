import fs from "node:fs";
let s = fs.readFileSync("说明.md","utf8");
const lines = s.split("\n");
const keep = lines.filter(l => !/^\| 加固全开还是「我无法满足此请求」/.test(l) && !/^\| `gemini-4-\*` 拒答时还点名/.test(l));
fs.writeFileSync("说明.md", keep.join("\n"), "utf8");
console.log("删掉两行 4A 时代新增的 FAQ（加固全开/4 系点名绕过）");
