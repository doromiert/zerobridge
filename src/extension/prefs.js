import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences, gettext as _} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class ZBridgePrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const page = new Adw.PreferencesPage();
        
        // --- Group 1: Connection ---
        const groupConnect = new Adw.PreferencesGroup({ title: _('Connection Settings') });

        const ipRow = new Adw.ActionRow({ title: _('Phone IP Address') });
        const ipEntry = new Gtk.Entry({ placeholder_text: '192.168.x.x:5555' });
        
        const saveBtn = new Gtk.Button({ label: _('Save & Connect') });
        saveBtn.add_css_class('suggested-action');
        
        saveBtn.connect('clicked', () => {
            const ip = ipEntry.get_text();
            if (ip) {
                try {
                    const proc = new Gio.Subprocess({
                        argv: ['zb-config', '-i', ip],
                        flags: Gio.SubprocessFlags.NONE
                    });
                    proc.init(null);
                    saveBtn.set_label(_('Saved!'));
                    setTimeout(() => saveBtn.set_label(_('Save & Connect')), 2000);
                } catch (e) {
                    console.error(e);
                }
            }
        });

        ipRow.add_suffix(ipEntry);
        ipRow.add_suffix(saveBtn);
        groupConnect.add(ipRow);
        
        // --- Group 2: Wireless Pairing ---
        const groupPair = new Adw.PreferencesGroup({ title: _('Wireless Pairing'), description: _('Use "Pair device with pairing code" on Android') });
        
        // Host:Port
        const pairIpRow = new Adw.ActionRow({ title: _('Pairing Address') });
        const pairIpEntry = new Gtk.Entry({ placeholder_text: '192.168.x.x:yyyy' });
        pairIpRow.add_suffix(pairIpEntry);
        groupPair.add(pairIpRow);

        // Code
        const codeRow = new Adw.ActionRow({ title: _('Pairing Code') });
        const codeEntry = new Gtk.Entry({ placeholder_text: '123456' });
        
        const pairBtn = new Gtk.Button({ label: _('Pair Now') });
        pairBtn.connect('clicked', () => {
             const addr = pairIpEntry.get_text();
             const code = codeEntry.get_text();
             
             if (addr && code) {
                 this._runPair(addr, code, pairBtn);
             }
        });
        
        codeRow.add_suffix(codeEntry);
        codeRow.add_suffix(pairBtn);
        groupPair.add(codeRow);

        page.add(groupConnect);
        page.add(groupPair);
        window.add(page);
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
                        btn.set_label(_('Success!'));
                        // Send system notification
                        const notif = new Gio.Subprocess({
                            argv: ['notify-send', 'ZBridge Pairing', `Successfully paired with ${addr}`],
                            flags: Gio.SubprocessFlags.NONE
                        });
                        notif.init(null);
                    } else {
                         btn.set_label(_('Failed'));
                         console.warn(stderr);
                    }
                } catch (e) {
                    btn.set_label(_('Error'));
                }
                setTimeout(() => {
                    btn.set_label(_('Pair Now'));
                    btn.set_sensitive(true);
                }, 3000);
            });
        } catch (e) {
            btn.set_label(_('Error'));
            btn.set_sensitive(true);
        }
    }
}