const User = require('../models/User');

async function getUser(userId) {
  const user = await User.findById(userId).select('-passwordHash').populate('teamIds');
  if (!user) {
    const err = new Error('User not found.');
    err.statusCode = 404;
    throw err;
  }
  return user;
}

async function getUsers({ role, teamId } = {}) {
  const query = {};
  if (role)   query.role    = role;
  if (teamId) query.teamIds = teamId;
  return User.find(query).select('-passwordHash').sort({ name: 1 });
}

async function updateSkills(targetUserId, skillTags, requestingUser) {
  const isAdmin = requestingUser.role === 'admin';
  const isSelf  = requestingUser._id.toString() === targetUserId;

  if (!isAdmin && !isSelf) {
    const err = new Error('You can only update your own skills.');
    err.statusCode = 403;
    throw err;
  }

  if (!Array.isArray(skillTags)) {
    const err = new Error('skillTags must be an array.');
    err.statusCode = 400;
    throw err;
  }

  const user = await User.findByIdAndUpdate(targetUserId, { skillTags }, { new: true }).select('-passwordHash');
  if (!user) {
    const err = new Error('User not found.');
    err.statusCode = 404;
    throw err;
  }

  return user;
}

module.exports = { getUser, getUsers, updateSkills };
