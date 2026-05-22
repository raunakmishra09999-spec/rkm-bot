const { EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');

module.exports = {
    async handleRegistration(message, client, db, config) {
        const channelName = message.channel.name;
        const match = channelName.match(/(\d{1,2})-(\d{2})(am|pm)-reg-(\d{1,2})-(\d{2})(am|pm)/i);
        
        if (!match) return;
        
        const currentHour = new Date().getHours();
        const openHour = this.parseTimeTo24h(match[1], match[2], match[3]);
        
        if (currentHour < openHour) {
            await message.delete();
            await message.channel.send(`${message.author}, ❌ This channel will open at **${match[1]}:${match[2]} ${match[3]}**!`);
            return;
        }
        
        const isLocked = await this.isChannelLocked(message.channel.id, db);
        if (isLocked) {
            await message.delete();
            return;
        }
        
        const lines = message.content.split('\n');
        const teamName = lines[0].replace('Team name -', '').trim();
        const players = lines.slice(2).filter(l => l.startsWith('@')).join(',');
        
        const registrations = await this.getRegistrations(message.channel.id, db);
        const slotNumber = registrations.length + 1;
        
        if (slotNumber > 25) {
            await message.delete();
            await message.channel.send(`${message.author}, ❌ Maximum 25 registrations reached! Channel is now locked.`);
            await this.lockChannel(message.channel);
            return;
        }
        
        db.run(`INSERT INTO registrations (channelId, userId, teamName, players, timestamp, slotNumber) 
                VALUES (?, ?, ?, ?, ?, ?)`,
            [message.channel.id, message.author.id, teamName, players, Date.now(), slotNumber]);
        
        await message.react('✅');
        await message.channel.send(`✅ **${teamName}** registered! Slot #${slotNumber}`);
        
        if (slotNumber === 25) {
            await this.lockChannel(message.channel);
            
            const teams = await this.getRegistrations(message.channel.id, db);
            let teamList = '## 🎮 **Registered Teams (Slot-wise)**\n';
            teams.forEach(team => {
                teamList += `**Slot ${team.slotNumber}:** ${team.teamName}\n`;
            });
            await message.channel.send(teamList);
            
            await this.showIdpChannelToRegistered(message.channel.id, client, db, config);
        }
    },
    
    parseTimeTo24h(hour, minute, ampm) {
        let h = parseInt(hour);
        if (ampm === 'pm' && h !== 12) h += 12;
        if (ampm === 'am' && h === 12) h = 0;
        return h;
    },
    
    async lockChannel(channel) {
        await channel.permissionOverwrites.edit(channel.guild.roles.everyone, {
            SendMessages: false
        });
    },
    
    async isChannelLocked(channelId, db) {
        return new Promise((resolve) => {
            db.get(`SELECT COUNT(*) as count FROM registrations WHERE channelId = ?`, [channelId], (err, row) => {
                resolve(row?.count >= 25);
            });
        });
    },
    
    getRegistrations(channelId, db) {
        return new Promise((resolve) => {
            db.all(`SELECT * FROM registrations WHERE channelId = ? ORDER BY slotNumber ASC`, [channelId], (err, rows) => {
                resolve(rows || []);
            });
        });
    },
    
    async showIdpChannelToRegistered(channelId, client, db, config) {
        const registrations = await this.getRegistrations(channelId, db);
        const registeredUsers = registrations.map(r => r.userId);
        
        const idpChannelId = this.getCorrespondingIdpChannel(channelId);
        const idpChannel = client.channels.cache.get(idpChannelId);
        
        if (idpChannel) {
            await idpChannel.permissionOverwrites.edit(idpChannel.guild.roles.everyone, {
                ViewChannel: false
            });
            
            for (const userId of registeredUsers) {
                const member = await idpChannel.guild.members.fetch(userId).catch(() => null);
                if (member) {
                    await idpChannel.permissionOverwrites.edit(member, {
                        ViewChannel: true
                    });
                }
            }
            
            const embed = new EmbedBuilder()
                .setTitle('🔐 **IDP Access**')
                .setDescription('Click the button below to get your ID Pass')
                .setColor(0xFF0000);
            
            const row = new ActionRowBuilder()
                .addComponents(
                    new ButtonBuilder()
                        .setCustomId('get_idp')
                        .setLabel('🎫 GET ID PASS')
                        .setStyle(ButtonStyle.Danger)
                );
            
            await idpChannel.send({ embeds: [embed], components: [row] });
        }
    },
    
    getCorrespondingIdpChannel(regChannelId) {
        const mapping = {
            '1503283979221074020': '1503283979221074021'
        };
        return mapping[regChannelId] || null;
    }
};
