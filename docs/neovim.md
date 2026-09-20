# Neovim setup

Lint your lyrics file in Neovim and get replacement suggestions, using
[nvim-lint](https://github.com/mfussenegger/nvim-lint).

## 1. Add the linter

```lua
require("lint").linters.lyrics = {
  cmd = "/path/to/lyrics-lint/.venv/bin/lyrics", -- or your `lyrics` install path
  args = { "lint", "-", "--json" },
  stdin = true,
  parser = function(output)
    local ok, decoded = pcall(vim.json.decode, output)
    if not ok then return {} end
    local severities = { info = vim.diagnostic.severity.INFO, warning = vim.diagnostic.severity.WARN }
    local diagnostics = {}
    for _, d in ipairs(decoded) do
      local suggestions = {}
      for _, s in ipairs(d.suggestions or {}) do
        table.insert(suggestions, { word = s.word, distance = s.distance ~= vim.NIL and s.distance or nil })
      end
      table.insert(diagnostics, {
        lnum = d.line - 1,
        col = d.col - 1,
        end_lnum = d.line - 1,
        end_col = d.end_col - 1,
        message = d.message,
        severity = severities[d.severity] or vim.diagnostic.severity.WARN,
        source = "lyrics-lint",
        user_data = { suggestions = suggestions },
      })
    end
    return diagnostics
  end,
}
```

## 2. Add a keymap to run it

It's not tied to a filetype, so trigger it manually:

```lua
vim.keymap.set("n", "<leader>ly", function()
  require("lint").try_lint("lyrics")
end, { desc = "Lint lyrics" })
```

## 3. (Optional) Add a keymap to fix a flagged word

Puts your cursor's flagged word into a picker, and replaces it with
whatever you choose:

```lua
vim.keymap.set("n", "<leader>lr", function()
  local bufnr = vim.api.nvim_get_current_buf()
  local row = vim.api.nvim_win_get_cursor(0)[1] - 1

  local diagnostics = vim.tbl_filter(function(d)
    return d.source == "lyrics-lint" and d.user_data.suggestions and #d.user_data.suggestions > 0
  end, vim.diagnostic.get(bufnr, { lnum = row }))

  if #diagnostics == 0 then
    vim.notify("No suggestions on this line", vim.log.levels.WARN)
    return
  end

  local d = diagnostics[1]
  local word = vim.api.nvim_buf_get_text(bufnr, d.lnum, d.col, d.end_lnum, d.end_col, {})[1]

  vim.ui.select(d.user_data.suggestions, {
    prompt = ("Replace '%s' with:"):format(word),
    format_item = function(item)
      if item.distance == nil then return item.word .. "  (unverified)" end
      if item.distance == 0 then return item.word .. "  (perfect rhyme)" end
      return item.word .. "  (close rhyme)"
    end,
  }, function(choice)
    if not choice then return end
    vim.api.nvim_buf_set_text(bufnr, d.lnum, d.col, d.end_lnum, d.end_col, { choice.word })
    require("lint").try_lint("lyrics")
  end)
end, { desc = "Replace flagged word with a suggested rhyme" })
```

## Using it

1. Open a lyrics file and press `<leader>ly`. It takes about a second.
2. Lines with rhyme problems get underlined, with a message explaining why.
3. Put your cursor on a flagged line and press `<leader>lr` to see and pick
   a replacement word.

**If diagnostic jump keys (like `]d`/`[d`) don't work on this file:** some
Neovim configs only bind those when an LSP server is attached, and lyrics
files don't have one. Make sure your diagnostic-jump keymaps aren't nested
inside an `LspAttach` block.
