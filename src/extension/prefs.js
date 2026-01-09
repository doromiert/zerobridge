import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import GObject from 'gi://GObject';
import {ExtensionPreferences, gettext as _} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class ZBridgePrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        this._settings = this.getSettings();
        const page = new Adw.PreferencesPage();

        // --- Group 1: Manage Connection ---
        const groupConnect = new Adw.PreferencesGroup({
            title: _('Connection Management'),
            description: _('Connect to a new device or manage saved phones.')
        });

        // 1. New Connection Row
        const ipRow = new Adw.EntryRow({
            title: _('New Connection (IP)'),
            input_purpose: Gtk.InputPurpose.FREE_FORM
        });

        const connectBtn = new Gtk.Button({
            label: _('Connect & Save'),
            valign: Gtk.Align.CENTER
        });
        connectBtn.add_css_class('suggested-action');

        connectBtn.connect('clicked', () => {
            const ip = ipRow.get_text();
            if (ip) {
                // Run connection command
                this._runCommand(['zb-config', '-i', ip], connectBtn, _('Connect & Save'), true, ip);
            }
        });

        ipRow.add_suffix(connectBtn);
        groupConnect.add(ipRow);

        // 2. Saved List Expander
        this._savedGroup = new Adw.ExpanderRow({
            title: _('Saved Phones'),
            subtitle: _('Click to quick-connect'),
            expanded: true
        });

        // Icon for the expander
        this._savedGroup.add_prefix(new Gtk.Image({ icon_name: 'phone-symbolic' }));
        
        groupConnect.add(this._savedGroup);

        // Initialize the list
        this._refreshSavedList();

        // Listen for external changes (optional, but good practice)
        this._settings.connect('changed::saved-ips', () => this._refreshSavedList());


        // --- Group 2: Camera Defaults ---
        const groupCam = new Adw.PreferencesGroup({
            title: _('Camera Defaults'),
            description: _('Set the default orientation for each camera lens.')
        });

        const orientations = ['0', '90', '180', '270', 'flip0', 'flip90', 'flip180', 'flip270'];
        const orientList = new Gtk.StringList({ strings: orientations });

        // Front
        const frontRow = new Adw.ComboRow({
            title: _('Default Front Orientation'),
            model: orientList,
        });
        frontRow.set_selected(5); // flip90
        frontRow.connect('notify::selected', () => {
             const selected = orientations[frontRow.get_selected()];
             this._runSilentCommand(['zb-config', '-F', selected]);
        });
        groupCam.add(frontRow);

        // Back
        const backRow = new Adw.ComboRow({
            title: _('Default Back Orientation'),
            model: orientList,
        });
        backRow.set_selected(7); // flip270
        backRow.connect('notify::selected', () => {
             const selected = orientations[backRow.get_selected()];
             this._runSilentCommand(['zb-config', '-B', selected]);
        });
        groupCam.add(backRow);


        // --- Group 3: Wireless Pairing ---
        const groupPair = new Adw.PreferencesGroup({
            title: _('Wireless Pairing'),
            description: _('Requires "Wireless Debugging" enabled in Android Developer Options.')
        });

        const pairIpRow = new Adw.EntryRow({
            title: _('Pairing Address'),
            input_purpose: Gtk.InputPurpose.FREE_FORM
        });

        const codeRow = new Adw.EntryRow({
            title: _('Pairing Code'),
            input_purpose: Gtk.InputPurpose.NUMBER
        });

        const pairBtn = new Gtk.Button({
            label: _('Pair'),
            valign: Gtk.Align.CENTER
        });
        pairBtn.add_css_class('suggested-action');

        pairBtn.connect('clicked', () => {
            const addr = pairIpRow.get_text();
            const code = codeRow.get_text();
            if (addr && code) this._runPair(addr, code, pairBtn);
        });

        codeRow.add_suffix(pairBtn);
        groupPair.add(pairIpRow);
        groupPair.add(codeRow);

        page.add(groupConnect);
        page.add(groupCam);
        page.add(groupPair);
        window.add(page);
    }

    _refreshSavedList() {
        // Clear current rows in the expander
        // Note: Adw.ExpanderRow doesn't have a clear(), so we remove rows one by one
        // Wait, currently Adw 1.4+ (Shell 45+)
        
        // Safety check: The easiest way to "refresh" without complexity is 
        // managing the rows manually.
        
        // Since we can't easily iterate and remove children from ExpanderRow in JS 
        // without getting Gtk internal children sometimes, we keep track of them.
        if (this._currentRows) {
            this._currentRows.forEach(row => this._savedGroup.remove(row));
        }
        this._currentRows = [];

        const savedIps = this._settings.get_value('saved-ips').deep_unpack();

        savedIps.forEach(ip => {
            const row = new Adw.ActionRow({ title: ip });
            
            // Connect Button (Icon)
            const connBtn = new Gtk.Button({
                icon_name: 'network-transmit-receive-symbolic',
                valign: Gtk.Align.CENTER,
                tooltip_text: _('Connect to this phone')
            });
            connBtn.add_css_class('flat');
            connBtn.connect('clicked', () => {
                this._runCommand(['zb-config', '-i', ip], connBtn, null, false, null);
            });
            row.add_suffix(connBtn);

            // Delete Button
            const delBtn = new Gtk.Button({
                icon_name: 'user-trash-symbolic',
                valign: Gtk.Align.CENTER,
                tooltip_text: _('Remove from list')
            });
            delBtn.add_css_class('flat');
            delBtn.add_css_class('destructive-action');
            
            delBtn.connect('clicked', () => {
                this._removeIp(ip);
            });
            row.add_suffix(delBtn);

            this._savedGroup.add_row(row);
            this._currentRows.push(row);
        });

        if (savedIps.length === 0) {
            this._savedGroup.set_subtitle(_('No phones saved yet'));
        } else {
            this._savedGroup.set_subtitle(_(`${savedIps.length} phone(s) saved`));
        }
    }

    _saveIp(ip) {
        let current = this._settings.get_value('saved-ips').deep_unpack();
        if (!current.includes(ip)) {
            current.push(ip);
            this._settings.set_value('saved-ips', new GObject.Variant('as', current));
            this._refreshSavedList();
        }
    }

    _removeIp(ip) {
        let current = this._settings.get_value('saved-ips').deep_unpack();
        const index = current.indexOf(ip);
        if (index > -1) {
            current.splice(index, 1);
            this._settings.set_value('saved-ips', new GObject.Variant('as', current));
            this._refreshSavedList();
        }
    }

    _runCommand(argv, button, defaultLabel, saveOnSuccess, ipToSave) {
        button.set_sensitive(false);
        const originalLabel = button.label; // Keep icon if label is null
        
        try {
            const proc = new Gio.Subprocess({
                argv: argv,
                flags: Gio.SubprocessFlags.NONE
            });
            proc.init(null);
            
            proc.wait_check_async(null, (proc, res) => {
                try {
                    proc.wait_check_finish(res);
                    // On Success
                    if (!button.icon_name) button.set_label(_('Success!'));
                    
                    if (saveOnSuccess && ipToSave) {
                        this._saveIp(ipToSave);
                    }

                } catch (e) {
                    console.error(e);
                    if (!button.icon_name) button.set_label(_('Failed'));
                }
                
                setTimeout(() => {
                    if (defaultLabel) button.set_label(defaultLabel);
                    button.set_sensitive(true);
                }, 1500);
            });
        } catch (e) {
            console.error(e);
            button.set_sensitive(true);
        }
    }

    _runSilentCommand(argv) {
        try {
            const proc = new Gio.Subprocess({ argv: argv, flags: Gio.SubprocessFlags.NONE });
            proc.init(null);
        } catch (e) { console.error(e); }
    }

    _runPair(addr, code, btn) {
        // ... (Same as original) ...
        btn.set_sensitive(false);
        btn.set_label(_('Pairing...'));

        try {
            const proc = new Gio.Subprocess({
                argv: ['adb', 'pair', addr, code],
                flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            });
            proc.init(null);

            proc.communicate_utf8_async(null, null, (proc, res) => {
                try {
                    const [, stdout, stderr] = proc.communicate_utf8_finish(res);
                    if (proc.get_successful()) {
                        btn.set_label(_('Paired!'));
                        this._saveIp(addr.split(':')[0]); // Auto-save paired IP? optional
                    } else {
                        btn.set_label(_('Failed'));
                    }
                } catch (e) {
                    btn.set_label(_('Error'));
                }

                setTimeout(() => {
                    btn.set_label(_('Pair'));
                    btn.set_sensitive(true);
                }, 3000);
            });
        } catch (e) {
            btn.set_label(_('Error'));
            btn.set_sensitive(true);
        }
    }
}