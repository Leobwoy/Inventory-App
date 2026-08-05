/*
 * Searchable single-select.
 *
 * Replaces Select2, which dragged in jQuery (~90KB) plus Select2 itself (~70KB)
 * over metered mobile data to power one dropdown on the sale form.
 *
 * Progressive enhancement by design: the original <select> stays in the DOM and
 * keeps its name and value, so the form posts identically and the page still
 * works with JavaScript off. Choosing an option writes to the <select> and
 * dispatches a 'change' event, so anything already listening on the select
 * keeps working unchanged.
 *
 * Enhance with: <select data-combobox data-combobox-placeholder="Search...">
 */
(function (window, document) {
    'use strict';

    var uid = 0;

    function Combobox(select) {
        this.select = select;
        this.listId = 'combobox-list-' + (++uid);
        this.matches = [];
        this.activeIndex = -1;

        var wrap = document.createElement('div');
        wrap.className = 'combobox';

        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control combobox-input';
        input.autocomplete = 'off';
        input.disabled = select.disabled;
        input.placeholder = select.getAttribute('data-combobox-placeholder') || 'Type to search';
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-controls', this.listId);

        // The page's <label> points at the native <select>, which is now
        // hidden - so the visible control had no accessible name at all, and
        // clicking the label focused nothing. Borrow the label's identity.
        var labelIds = [];
        var listId = this.listId;
        Array.prototype.forEach.call(select.labels || [], function (label, index) {
            if (!label.id) {
                label.id = listId + '-label-' + index;
            }
            labelIds.push(label.id);
            label.addEventListener('click', function (event) {
                event.preventDefault();
                input.focus();
            });
        });
        if (labelIds.length) {
            input.setAttribute('aria-labelledby', labelIds.join(' '));
        } else if (select.getAttribute('aria-label')) {
            input.setAttribute('aria-label', select.getAttribute('aria-label'));
        }

        var list = document.createElement('ul');
        list.className = 'combobox-list';
        list.id = this.listId;
        list.hidden = true;
        list.setAttribute('role', 'listbox');

        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(input);
        wrap.appendChild(list);
        wrap.appendChild(select);

        // display:none still submits the value; only `disabled` would drop it.
        select.classList.add('combobox-native');

        this.wrap = wrap;
        this.input = input;
        this.list = list;

        this.build();
        this.bind();
        this.syncFromSelect();

        select.combobox = this;
    }

    Combobox.prototype.build = function () {
        var self = this;
        this.list.textContent = '';
        Array.prototype.forEach.call(this.select.options, function (option, index) {
            var item = document.createElement('li');
            item.className = 'combobox-option';
            item.textContent = option.textContent;
            item.dataset.index = index;
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', 'false');
            self.list.appendChild(item);
        });
    };

    /* Mirror whatever the <select> currently holds into the visible input. */
    Combobox.prototype.syncFromSelect = function () {
        var option = this.select.options[this.select.selectedIndex];
        this.input.value = option ? option.textContent : '';
    };

    Combobox.prototype.filter = function (term) {
        var needle = term.trim().toLowerCase();
        this.matches = [];
        var self = this;
        Array.prototype.forEach.call(this.list.children, function (item) {
            var hit = !needle || item.textContent.toLowerCase().indexOf(needle) !== -1;
            item.hidden = !hit;
            if (hit) {
                self.matches.push(item);
            }
        });
        this.setActive(this.matches.length ? 0 : -1);
    };

    Combobox.prototype.setActive = function (index) {
        var self = this;
        this.activeIndex = index;
        this.matches.forEach(function (item, i) {
            var active = i === index;
            item.classList.toggle('is-active', active);
            if (active) {
                self.input.setAttribute('aria-activedescendant', self.listId + '-' + i);
                item.id = self.listId + '-' + i;
                if (item.offsetTop < self.list.scrollTop ||
                    item.offsetTop + item.offsetHeight > self.list.scrollTop + self.list.clientHeight) {
                    item.scrollIntoView({ block: 'nearest' });
                }
            }
        });
        if (index === -1) {
            this.input.removeAttribute('aria-activedescendant');
        }
    };

    Combobox.prototype.open = function () {
        if (this.select.disabled) {
            return;
        }
        this.filter('');
        this.list.hidden = false;
        this.input.setAttribute('aria-expanded', 'true');
        // Show the selected option as active rather than the first match.
        var current = this.matches.indexOf(this.list.children[this.select.selectedIndex]);
        if (current !== -1) {
            this.setActive(current);
        }
    };

    Combobox.prototype.close = function () {
        this.list.hidden = true;
        this.input.setAttribute('aria-expanded', 'false');
        this.input.removeAttribute('aria-activedescendant');
        // Discard a half-typed search term; the select is the source of truth.
        this.syncFromSelect();
    };

    Combobox.prototype.choose = function (item) {
        var index = parseInt(item.dataset.index, 10);
        var option = this.select.options[index];
        if (!option) {
            return;
        }
        Array.prototype.forEach.call(this.list.children, function (li) {
            li.setAttribute('aria-selected', 'false');
        });
        item.setAttribute('aria-selected', 'true');
        this.select.selectedIndex = index;
        this.close();
        this.select.dispatchEvent(new Event('change', { bubbles: true }));
    };

    Combobox.prototype.bind = function () {
        var self = this;

        this.input.addEventListener('focus', function () {
            self.open();
            self.input.select();
        });

        this.input.addEventListener('input', function () {
            if (self.list.hidden) {
                self.list.hidden = false;
                self.input.setAttribute('aria-expanded', 'true');
            }
            self.filter(self.input.value);
        });

        this.input.addEventListener('keydown', function (event) {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                if (self.list.hidden) {
                    self.open();
                    return;
                }
                var step = event.key === 'ArrowDown' ? 1 : -1;
                var next = self.activeIndex + step;
                if (next >= 0 && next < self.matches.length) {
                    self.setActive(next);
                }
            } else if (event.key === 'Enter') {
                if (!self.list.hidden && self.activeIndex !== -1) {
                    // Only swallow Enter when it is picking an option, so the
                    // key still submits the form the rest of the time.
                    event.preventDefault();
                    self.choose(self.matches[self.activeIndex]);
                }
            } else if (event.key === 'Escape') {
                if (!self.list.hidden) {
                    event.stopPropagation();
                    self.close();
                }
            } else if (event.key === 'Tab') {
                self.close();
            }
        });

        // mousedown, not click: it lands before the input's blur handler.
        this.list.addEventListener('mousedown', function (event) {
            var item = event.target.closest('.combobox-option');
            if (item) {
                event.preventDefault();
                self.choose(item);
            }
        });

        this.input.addEventListener('blur', function () {
            self.close();
        });
    };

    /* Enhance every unenhanced [data-combobox] inside root. Safe to re-run. */
    Combobox.enhance = function (root) {
        var scope = root || document;
        var selects = scope.querySelectorAll('select[data-combobox]:not(.combobox-native)');
        Array.prototype.forEach.call(selects, function (select) {
            new Combobox(select);
        });
    };

    window.Combobox = Combobox;

    document.addEventListener('DOMContentLoaded', function () {
        Combobox.enhance(document);
    });
})(window, document);
