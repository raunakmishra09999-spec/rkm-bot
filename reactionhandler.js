module.exports = {
    async validateAndReact(message) {
        const lines = message.content.split('\n').map(l => l.trim());
        
        const isValid = 
            lines[0]?.startsWith('Team name -') &&
            lines[1]?.startsWith('Team player name -') &&
            lines[2]?.startsWith('@') &&
            lines[3]?.startsWith('@') &&
            lines[4]?.startsWith('@') &&
            lines[5]?.startsWith('@');
        
        if (isValid) {
            await message.react('✅');
        } else {
            await message.react('❌');
            setTimeout(async () => {
                await message.delete();
                const warning = await message.channel.send(`${message.author}, ❌ **Wrong format!** Use:\n\`\`\`\nTeam name - [Your Team Name]\nTeam player name -\n@Player1\n@Player2\n@Player3\n@Player4\n\`\`\``);
                setTimeout(() => warning.delete(), 10000);
            }, 3000);
        }
    }
};
