import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences, gettext as _} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class ZBridgePrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const page = new Adw.PreferencesPage();

        // --- Group 1: Connection ---
        const groupConnect = new Adw.PreferencesGroup({
            title: _('Connection Settings'),
            description: _('Configure the target IP of your Android device.')
        });

        // NATIVE ADWAITA: Use Adw.EntryRow instead of ActionRow + Entry
        const ipRow = new Adw.EntryRow({
            title: _('Phone IP Address'),
            input_purpose: Gtk.InputPurpose.FREE_FORM
        });

        const saveBtn = new Gtk.Button({
            label: _('Save & Connect'),
            valign: Gtk.Align.CENTER
        });
        saveBtn.add_css_class('suggested-action'); // Blue accent color

        saveBtn.connect('clicked', () => {
            const ip = ipRow.get_text();
            if (ip) {
                this._runCommand(
                    ['zb-config', '-i', ip],
                    saveBtn,
                    _('Save & Connect')
                );
            }
        });

        ipRow.add_suffix(saveBtn);
        groupConnect.add(ipRow);

        // --- Group 2: Camera Defaults ---
        const groupCam = new Adw.PreferencesGroup({
            title: _('Camera Defaults'),
            description: _('Set the default orientation for each camera lens.')
        });

        const orientations = ['0', '90', '180', '270', 'flip0', 'flip90', 'flip180', 'flip270'];
        const orientList = new Gtk.StringList({ strings: orientations });

        // Front Camera Default
        const frontRow = new Adw.ComboRow({
            title: _('Default Front Orientation'),
            model: orientList,
        });
        // Default index 5 corresponds to 'flip90'
        frontRow.set_selected(5); 

        frontRow.connect('notify::selected', () => {
             const selected = orientations[frontRow.get_selected()];
             this._runSilentCommand(['zb-config', '-F', selected]);
        });
        groupCam.add(frontRow);

        // Back Camera Default
        const backRow = new Adw.ComboRow({
            title: _('Default Back Orientation'),
            model: orientList,
        });
        // Default index 7 corresponds to 'flip270'
        backRow.set_selected(7);

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

        // Pairing Address
        const pairIpRow = new Adw.EntryRow({
            title: _('Pairing Address'),
            text: '', 
            input_purpose: Gtk.InputPurpose.FREE_FORM
        });

        // Pairing Code
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
            if (addr && code) {
                this._runPair(addr, code, pairBtn);
            }
        });

        codeRow.add_suffix(pairBtn);

        groupPair.add(pairIpRow);
        groupPair.add(codeRow);

        page.add(groupConnect);
        page.add(groupCam);
        page.add(groupPair);
        window.add(page);
    }

    /**
     * Generic helper to run a subprocess and update button state
     */
    _runCommand(argv, button, defaultLabel) {
        button.set_sensitive(false);
        
        try {
            const proc = new Gio.Subprocess({
                argv: argv,
                flags: Gio.SubprocessFlags.NONE
            });
            proc.init(null);
            
            proc.wait_check_async(null, (proc, res) => {
                try {
                    proc.wait_check_finish(res);
                    button.set_label(_('Success!'));
                } catch (e) {
                    console.error(e);
                    button.set_label(_('Failed'));
                }
                
                setTimeout(() => {
                    button.set_label(defaultLabel);
                    button.set_sensitive(true);
                }, 2000);
            });
        } catch (e) {
            console.error(e);
            button.set_label(_('Error'));
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
                        
                        // Optional: Send system notification
                        try {
                            const notif = new Gio.Subprocess({
                                argv: ['notify-send', 'ZBridge', `Successfully paired: ${addr}`],
                                flags: Gio.SubprocessFlags.NONE
                            });
                            notif.init(null);
                        } catch(e) {}

                    } else {
                        btn.set_label(_('Failed'));
                        console.warn(stderr);
                    }
                } catch (e) {
                    btn.set_label(_('Error'));
                    console.error(e);
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