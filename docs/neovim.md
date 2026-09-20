# Neovim (nvim-lint) integration

`lyrics lint --json` is built for editor integration: it reads text on
stdin and emits a JSON array of diagnostics, each shaped as:

```json
{
  "line": 3,
  "col": 14,
  "end_col": 16,
  "severity": "warning",
  "code": "no-rhyme-partner",
  "message": "'me' has no rhyme partner in this stanza (closest pattern distance 3)",
  "suggestions": [
    { "word": "crossed", "distance": 0 },
    { "word": "abort", "distance": 1 }
  ]
}
```

`distance: 0` = perfect rhyme, `1`/`2` = slant/weak-slant, `null` = an
unverified suffix-based fallback (used when the flagged word itself isn't
in the pronunciation dictionary). `line`/`col`/`end_col` are 1-indexed,
`end_col` exclusive.

## Linter definition

Example [nvim-lint](https://github.com/mfussenegger/nvim-lint) linter
definition (adjust `cmd` to your install path, or use `uvx --from
git+https://github.com/rockerBOO/lyrics-lint lyrics` instead of a local
venv binary):

```lua
require("lint").linters.lyrics = {
  cmd = "/path/to/lyrics-lint/.venv/bin/lyrics",
  args = { "lint", "-", "--json" },
  stdin = true,
  stream = "stdout",
  ignore_exitcode = true,
  parser = function(output)
    local ok, decoded = pcall(vim.json.decode, output)
    if not ok or type(decoded) ~= "table" then
      return {}
    end
    local severities = { info = vim.diagnostic.severity.INFO, warning = vim.diagnostic.severity.WARN }
    local diagnostics = {}
    for _, d in ipairs(decoded) do
      local suggestions = {}
      for _, s in ipairs(d.suggestions or {}) do
        table.insert(suggestions, {
          word = s.word,
          -- vim.json.decode maps JSON null to the vim.NIL sentinel,
          -- not Lua nil, so normalize it here.
          distance = s.distance ~= vim.NIL and s.distance or nil,
        })
      end
      table.insert(diagnostics, {
        lnum = d.line - 1,
        col = d.col - 1,
        end_lnum = d.line - 1,
        end_col = d.end_col - 1,
        message = d.message,
        code = d.code,
        user_data = { lsp = { code = d.code }, suggestions = suggestions },
        severity = severities[d.severity] or vim.diagnostic.severity.WARN,
        source = "lyrics-lint",
      })
    end
    return diagnostics
  end,
}
```

It isn't tied to any filetype by default — run it on demand, e.g.
`require("lint").try_lint("lyrics")` bound to a keymap, since it's
async (~1 s: cmudict loads fresh per invocation) and would be noisy if
run on every markdown save.

## Picking a replacement

Since each diagnostic carries ranked `suggestions`, you can build a picker
that replaces the flagged word directly. Given a diagnostic under the
cursor (`vim.diagnostic.get(bufnr, { lnum = row })`, filtered to
`source == "lyrics-lint"`), pull `diagnostic.user_data.suggestions` and
feed it to `vim.ui.select`:

```lua
vim.keymap.set("n", "<leader>lr", function()
  local bufnr = vim.api.nvim_get_current_buf()
  local row = vim.api.nvim_win_get_cursor(0)[1] - 1

  local diagnostics = vim.tbl_filter(function(d)
    return d.source == "lyrics-lint"
      and d.user_data
      and d.user_data.suggestions
      and #d.user_data.suggestions > 0
  end, vim.diagnostic.get(bufnr, { lnum = row }))

  if #diagnostics == 0 then
    vim.notify("No lyrics-lint suggestions on this line", vim.log.levels.WARN)
    return
  end

  local diagnostic = diagnostics[1]
  local word = vim.api.nvim_buf_get_text(
    bufnr, diagnostic.lnum, diagnostic.col, diagnostic.end_lnum, diagnostic.end_col, {}
  )[1]

  vim.ui.select(diagnostic.user_data.suggestions, {
    prompt = ("Replace '%s' with:"):format(word),
    format_item = function(item)
      if item.distance == nil then
        return item.word .. "  [unverified]"
      elseif item.distance == 0 then
        return item.word .. "  [perfect]"
      else
        return item.word .. ("  [slant d%d]"):format(item.distance)
      end
    end,
  }, function(choice)
    if not choice then
      return
    end
    vim.api.nvim_buf_set_text(
      bufnr, diagnostic.lnum, diagnostic.col, diagnostic.end_lnum, diagnostic.end_col, { choice.word }
    )
    require("lint").try_lint("lyrics")
  end)
end, { desc = "Lyrics: pick a rhyme replacement for this line" })
```

## Diagnostic navigation

`vim.diagnostic.jump`/`vim.diagnostic.open_float` work on any diagnostic
source, not just LSP — if your navigation keymaps are only bound inside an
`LspAttach` autocmd, they won't exist on buffers with no LSP client
attached (e.g. a plain lyrics file linted only by nvim-lint). Bind them
globally instead:

```lua
vim.keymap.set("n", "<Leader>di", vim.diagnostic.open_float)
vim.keymap.set("n", "<Leader>k", function()
  vim.diagnostic.jump({ float = true, count = -1 })
end)
vim.keymap.set("n", "<Leader>j", function()
  vim.diagnostic.jump({ float = true, count = 1 })
end)
```
