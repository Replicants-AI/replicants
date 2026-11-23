// Tiny 3x5 bitmap alphabet; canvas pixels remain integer-aligned at all display DPIs.
const rows: Record<string, string> = {
  A:'010101111101101',B:'110101110101110',C:'011100100100011',D:'110101101101110',E:'111100110100111',F:'111100110100100',
  G:'011100101101011',H:'101101111101101',I:'111010010010111',J:'001001001101010',K:'101101110101101',L:'100100100100111',
  M:'101111111101101',N:'101111111111101',O:'010101101101010',P:'110101110100100',Q:'010101101111011',R:'110101110101101',
  S:'011100010001110',T:'111010010010010',U:'101101101101111',V:'101101101101010',W:'101101111111101',X:'101101010101101',
  Y:'101101010010010',Z:'111001010100111',0:'111101101101111',1:'010110010010111',2:'110001010100111',3:'110001010001110',
  4:'101101111001001',5:'111100110001110',6:'011100111101111',7:'111001010010010',8:'111101111101111',9:'111101111001110',
  '?':'110001010000010','!':'010010010000010','.':'000000000000010',',':'000000000010100',':':'000010000010000',
  "'":'010010000000000','-':'000000111000000','/':'001001010100100','(':'001010010010001',')':'100010010010100',' ':'000000000000000',
};
export function pixelText(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, size = 2) {
  for (const [i, char] of [...text.toUpperCase()].entries()) {
    const pattern = rows[char] ?? rows['?'];
    for (let n = 0; n < 15; n++) if (pattern[n] === '1') ctx.fillRect(Math.round(x + (i * 4 + n % 3) * size), Math.round(y + Math.floor(n / 3) * size), size, size);
  }
}
// Speech arrives already fitted to 240 characters at a word boundary; show all of it.
export function wrap(text: string, columns = 28) {
  const lines: string[] = []; let line = '';
  for (const word of text.slice(0, 240).split(/\s+/)) {
    if ((line + ' ' + word).trim().length > columns && line) { lines.push(line); line = ''; }
    line = (line + ' ' + word).trim();
  }
  if (line) lines.push(line);
  return lines.slice(0, 11);
}
