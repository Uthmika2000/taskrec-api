const express = require('express');
const router = express.Router();
const User = require('../models/User');
const { authMiddleware } = require('../middleware/authMiddleware');

// GET /api/users/:id
router.get('/:id', authMiddleware, async (req, res, next) => {
  try {
    const user = await User.findById(req.params.id).select('-passwordHash').populate('teamIds');
    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }
    res.json({ success: true, data: user });
  } catch (error) {
    next(error);
  }
});

// PATCH /api/users/:id/skills
router.patch('/:id/skills', authMiddleware, async (req, res, next) => {
  try {
    // Users can only update their own skills, admins can update anyone
    const targetUserId = req.params.id;
    const isAdmin = req.user.role === 'admin';
    const isSelf = req.user._id.toString() === targetUserId;

    if (!isAdmin && !isSelf) {
      return res.status(403).json({ success: false, message: 'You can only update your own skills.' });
    }

    const { skillTags } = req.body;
    if (!Array.isArray(skillTags)) {
      return res.status(400).json({ success: false, message: 'skillTags must be an array.' });
    }

    const user = await User.findByIdAndUpdate(
      targetUserId,
      { skillTags },
      { new: true }
    ).select('-passwordHash');

    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }

    res.json({ success: true, data: user });
  } catch (error) {
    next(error);
  }
});

// GET /api/users (list all developers for recommendation)
router.get('/', authMiddleware, async (req, res, next) => {
  try {
    const { role, teamId } = req.query;
    const query = {};
    if (role) query.role = role;
    if (teamId) query.teamIds = teamId;

    const users = await User.find(query).select('-passwordHash').sort({ name: 1 });
    res.json({ success: true, data: users });
  } catch (error) {
    next(error);
  }
});

module.exports = router;