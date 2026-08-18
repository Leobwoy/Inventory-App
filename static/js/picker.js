/*
 * Choosing a product, in a dialog.
 *
 * The reason this exists rather than a dropdown in the row: five columns do not
 * fit. Measured at 1440px - a very ordinary laptop - the product cell got 130px
 * and the input inside it 98px, while the longest product name needs about 160.
 * You would need a screen around 1500px wide before a search box in a table cell
 * showed a whole product name, so the box read "BelA" and there was no width to
 * be found anywhere on the row.
 *
 * The <select> stays. It keeps its name, it keeps posting, and it stays the
 * source of truth - the dialog only writes to it and fires an ordinary bubbling
 * 'change', so every listener already written against that carries on working.
 * With no JavaScript the select is never hidden and the page degrades to the
 * plain dropdown it has always been.
 *
 * Keyboard and filtering are modelled on the searchable-dropdown widget this
 * replaced (static/js/combobox.js, deleted once nothing used it - see git
 * history). The one thing not carried over is how the list is positioned: that
 * list floated at `position: absolute; max-height: 15rem` and would clip inside
 * a scrolling modal body, so this one is permanently open and fills the dialog.
 */
(function (window, document) {
    'use strict';

    var DIALOG_ID = 'product-picker';

    function Picker(root) {
        this.root = root;
        this.input = root.querySelector('.picker-search');
        this.list = root.querySelector('.picker-list');
        this.empty = root.querySelector('.picker-empty');
        this.title = root.querySelector('.picker-title');
        this.options = [];          // {value, label, meta, el}
        this.matches = [];
        this.activeIndex = -1;
        this.target = null;         // the <select> being written to
        this.modal = null;
        this.bind();
    }

    /* Rebuilt from whichever select opened it, so one dialog serves every row
       and a page that adds rows later needs no extra wiring. */
    Picker.prototype.loadFrom = function (select) {
        var self = this;
        this.target = select;
        this.list.innerHTML = '';
        this.options = [];

        Array.prototype.forEach.call(select.options, function (option, index) {
            // The empty "choose one" entry is what the dialog replaces; offering
            // it as something to pick would just be a way to unset the row.
            if (!option.value || option.value === '0') {
                return;
            }
            var el = document.createElement('li');
            el.className = 'picker-option';
            el.setAttribute('role', 'option');
            el.setAttribute('aria-selected', String(index === select.selectedIndex));
            el.dataset.index = String(index);

            var name = document.createElement('span');
            name.className = 'picker-option-name';
            name.textContent = option.textContent.trim();
            // Kept on the row so filtering has something to match that is not
            // the whole rendered line. See Picker.prototype.filter.
            el.dataset.name = name.textContent.toLowerCase();
            el.appendChild(name);

            // Price and stock come off the option as data attributes when the
            // page has them. Nothing here fetches; the server already sent it.
            if (option.dataset.meta) {
                var meta = document.createElement('span');
                meta.className = 'picker-option-meta';
                meta.textContent = option.dataset.meta;
                el.appendChild(meta);
            }

            self.list.appendChild(el);
            self.options.push(el);
        });

        this.input.value = '';
        this.filter('');
    };

    Picker.prototype.filter = function (term) {
        var needle = term.trim().toLowerCase();
        this.matches = [];
        var self = this;
        this.options.forEach(function (el) {
            // The name only. `el.textContent` also carries the meta line - the
            // price and the stock count - so typing "44" matched every product
            // that happened to cost 44 something, and since stock started
            // reading "13 cartons + 6 bottles" the word "cartons" matched every
            // packed product in the catalogue.
            var hit = !needle || (el.dataset.name || '').indexOf(needle) !== -1;
            el.hidden = !hit;
            if (hit) {
                self.matches.push(el);
            }
        });
        // Said out loud, rather than leaving an empty box. A search that finds
        // nothing looks identical to one that has not run.
        if (this.empty) {
            this.empty.hidden = this.matches.length > 0;
        }
        this.setActive(this.matches.length ? 0 : -1);
    };

    Picker.prototype.setActive = function (index) {
        this.activeIndex = index;
        this.matches.forEach(function (el, i) {
            el.classList.toggle('is-active', i === index);
        });
        var active = this.matches[index];
        if (active && active.scrollIntoView) {
            active.scrollIntoView({ block: 'nearest' });
        }
    };

    Picker.prototype.choose = function (el) {
        if (!el || !this.target) {
            return;
        }
        this.target.selectedIndex = parseInt(el.dataset.index, 10);
        // The same event the combobox dispatched, so the price lookup, the line
        // total and the running total all update through the listeners that
        // already exist rather than through anything this file knows about.
        this.target.dispatchEvent(new Event('change', { bubbles: true }));
        this.hide();
    };

    Picker.prototype.open = function (select, label) {
        this.loadFrom(select);
        if (this.title && label) {
            this.title.textContent = label;
        }
        if (window.bootstrap && window.bootstrap.Modal) {
            this.modal = window.bootstrap.Modal.getOrCreateInstance(this.root);
            this.modal.show();
        } else {
            // No Bootstrap for some reason: better an unstyled panel on the page
            // than a button that does nothing at all.
            this.root.classList.add('picker-fallback');
        }
    };

    Picker.prototype.hide = function () {
        if (this.modal) {
            this.modal.hide();
        } else {
            this.root.classList.remove('picker-fallback');
        }
    };

    Picker.prototype.bind = function () {
        var self = this;

        this.input.addEventListener('input', function () {
            self.filter(self.input.value);
        });

        this.input.addEventListener('keydown', function (event) {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                var next = self.activeIndex + (event.key === 'ArrowDown' ? 1 : -1);
                if (next >= 0 && next < self.matches.length) {
                    self.setActive(next);
                }
            } else if (event.key === 'Enter') {
                // Only when something is actually highlighted. Otherwise Enter
                // in a search box inside a form would submit the sale.
                event.preventDefault();
                if (self.activeIndex !== -1) {
                    self.choose(self.matches[self.activeIndex]);
                }
            }
        });

        this.list.addEventListener('click', function (event) {
            var el = event.target.closest('.picker-option');
            if (el) {
                self.choose(el);
            }
        });

        // Bootstrap moves focus to the dialog; put it in the search box, which
        // is the only thing anyone opened this to use.
        this.root.addEventListener('shown.bs.modal', function () {
            self.input.focus();
        });
    };

    var instance = null;

    function picker() {
        if (!instance) {
            var root = document.getElementById(DIALOG_ID);
            if (root) {
                instance = new Picker(root);
            }
        }
        return instance;
    }

    /* One delegated listener on the document, so rows added after load work
       without being wired up individually. */
    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-picker-for]');
        if (!button) {
            return;
        }
        var row = button.closest('[data-line]') || document;
        var select = row.querySelector(button.dataset.pickerFor);
        var p = picker();
        if (select && p) {
            event.preventDefault();
            p.open(select, button.dataset.pickerTitle || 'Choose a product');
        }
    });

    /* Keeps the row's visible text in step with its select. Exported because
       each page decides for itself what a chosen line should read. */
    window.ProductPicker = {
        /* Marks the page as scripted, which is what hides the raw selects. A
           page that never reaches this keeps them, and stays usable. */
        enhance: function (root) {
            var scope = root || document;
            var selects = scope.querySelectorAll('select[data-picker-select]');
            Array.prototype.forEach.call(selects, function (select) {
                var line = select.closest('[data-line]');
                if (line) {
                    line.classList.add('line-enhanced');
                }
            });
        },
        /* The chosen product's label, or null when nothing is chosen yet. */
        labelOf: function (select) {
            var option = select.options[select.selectedIndex];
            return option && option.value && option.value !== '0'
                ? option.textContent.trim() : null;
        },
    };

    document.addEventListener('DOMContentLoaded', function () {
        window.ProductPicker.enhance(document);
    });
})(window, document);
