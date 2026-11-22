import fs from "node:fs";
let s = fs.readFileSync("app.js","utf8");
const from = "  const fillLen = aiFill().sysOn ? Math.min(fillChars('sys') || 0, fillSrc('sys').length) + fillWrapChars('sys') : 0;";
const to   = "  const fillLen = aiFill().sysOn ? Math.min(fillChars('sys') || 0, fillSrc('sys').length) : 0;";
if(!s.includes(from)) throw new Error("找不到 renderCtxStat 的 fillLen 行");
s = s.replace(from, to);
fs.writeFileSync("app.js", s, "utf8");
console.log("renderCtxStat 去掉 fillWrapChars（包裹字数）");
